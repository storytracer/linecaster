# Phase 6 design (working document)

Interfaces for phase 6 of [the plan](refactoring.md): tests and engine hygiene. Removed with the plan when the
refactoring is done. Terms are the [glossary](../reference/glossary.md)'s. No behavior changes: outputs, flags and
block APIs stay as they are (the goldens; the suite).

## 1. `linecaster.testing`

A public module for engine packages, derivatives and linecaster's own tests. It imports pytest lazily (only the
helpers that need it); importing `linecaster.testing` must not load datatrove's executors, torch or any engine.

- `sample_page(width=..., height=..., lines=...)` and `sample_document(...)`: a small synthetic page image (PIL,
  printed text boxes) and its datatrove `Document` (today's `conftest.py` helpers move here; `conftest.py` imports
  them). `sample_transcription()` (today's `make_transcription`).
- Fake CPU engines, one per model step, deterministic and dependency-free, registered under ids
  `fake.<step>.v1` only when the test helper `register_fakes()` is called (never through entry points):
  `FakeLayoutEngine` (one text region per page or a fixed grid), `FakeLineEngine` (lines from the sample's known
  boxes or a fixed split of each region), `FakeRecognitionEngine` (text from the line id), `FakeTableEngine`,
  `FakeFormulaEngine`; and `fake_chat_server()` (a context manager: an OpenAI-compatible server on loopback that
  answers from a function), replacing the copies in `tests/` (`FakeLines`, `FakeText`, `FakeTables`, `FakeChat`).
- `check_engine(engine_cls, *, options=None, image=None, transcription=None)`: engine conformance. Checks: the
  `engine_id` pattern `<provider>.<step>[.<variant>].v<n>` and its step in the catalog's steps; `capabilities`
  (unit, produces) present and in the vocabulary; `Options` a pydantic model whose fields all have descriptions;
  `load()` then `__call__` returns a `Transcription` with only the declared parts added (compared like a block
  contract), its input not mutated, a `StepInfo` with the engine id and only `MEASUREMENTS` keys, the same result
  on a second call (determinism). Rule engines: the page or item protocol of their unit.
- `check_block(block, docs=None)`: block conformance: `contract()` present; on the sample pages, only declared
  parts change (`run_pages`); `to_dict()` JSON-serializable and stable; the block pickles with dill before
  `warm_up()` (datatrove's executors pickle pipelines); `warm_up()` idempotent; a failing page carries an error and
  passes later model blocks.
- Every built-in engine and every public block gets a conformance test through these (parametrized).

## 2. Markers and layout

- Registered markers (`--strict-markers`): `gpu` (needs a CUDA device), `network` (downloads weights or reaches the
  internet), `slow` (over ~10 s), `parity` (compares against goldens). The default run (`uv run pytest`) runs
  everything collectable and skips `gpu`/`network` tests automatically when the device or the network is missing
  (a conftest hook), so nothing changes for spark; CI runs `-m "not gpu and not network and not parity"`.
- The two PEP 723 test scripts (`tests/test_engines_catalog.py`, `tests/test_line_recognizers.py`) stay where
  they are (they need the engines' environments), but carry the markers and use `linecaster.testing`.

## 3. Per-engine tests and engine hygiene

- `engines/<engine>/tests/`: the engine's conformance (`check_engine`) and its own unit tests, run in the
  engine's environment (`uv run --project engines/<engine> pytest engines/<engine>/tests` or through the PEP 723
  script that installs it; whichever works without changing torch; document the command in the engine README).
  Tests that need weights are `network`, tests that need a GPU `gpu`.
- Engines depend only on linecaster's public engine API: `linecaster.data` (data model and geometry) and a new
  `linecaster.engines.api` (the `Engine` base or protocol and `Capabilities` if they live elsewhere today, and
  the weight helpers engines use now: `weights_of`, `hf_file`, `hf_snapshot`, a `model_entry(id)` for catalog
  lookups). A test (like `tests/test_import_rule.py`) reads the engine packages with `ast` and fails on any other
  `linecaster.*` import.
- Each engine package: its own version (`0.1.0`), a compatible-linecaster range in its dependencies
  (`linecaster>=0.1,<0.2`), its README (phase 5's) with the install command and the test command.
- Install hints: when a preset needs an engine that is not installed, the `CatalogError` names the package that
  provides it and the pipeline scripts whose environments install it (engine packages are not on PyPI; e.g.
  "`kraken.recognition.v1` is in `linecaster-kraken`, which `pipelines/transcribe_modular.py` installs"). The
  mapping engine id → package comes from what the catalog already knows (`code.Engine.package`).

## 4. CPU CI

- `.github/workflows/ci.yml` (a "CI workflow" in the glossary's terms): on push and pull request to main; uv
  (pinned to the project's `required-version`), Python 3.12; `uv sync --locked`; `uv run pytest -m "not gpu and
  not network and not parity"`; `uv run linecaster docs --check`; `uv run linecaster catalog verify`;
  `uv run --group docs mkdocs build --strict`. No engine environments in CI (torch is too large); the engines'
  conformance runs locally. No secrets.

## 5. Ray Data spike

- Question: could a pipeline's per-page blocks run as Ray Data `map_batches` (actors per model block, streaming
  between them) instead of datatrove's Ray executor, and what would it gain (GPU sharing across blocks, back
  pressure) or lose (datatrove's resume, logs, stats, stage cutting)?
- A script `tests/integration/ray_data_spike.py` (not collected) runs the squiddle blocks in-process on the
  sample-60 pages through Ray Data on spark and compares the page records with a normal run (same outputs?) and
  the wall time; the finding goes to NOTES.md as a dated entry, facts only, with a recommendation. No code in
  `src/`.

## 6. Fixes found in phase 5

Found while generating the block pages; verify each, then fix it with a test (`CHANGELOG.md`, Fixed). Contract
mismatches are what `check_block` should catch, so its tests come first and these make them pass.

1. `blocks/base/page.py` `image_bytes(doc)` returns the `doc` itself when the page has no image media.
2. `ImageConverter` without `keep_bytes` empties `doc.media`, but its contract replaces only `metadata`: the builder
   still treats `image` as available to later blocks.
3. `PageRecordReader(fetch_images=True)` and `ImageFetcher` drop the `#fragment` of `page.image.uri`: for records
   from `PdfReader` (`file.pdf#page=n`) or `ImageParquetReader` with embedded bytes they would fetch the whole
   file. Fetch by fragment where it can be resolved (a PDF page: render it, as `PdfReader` does; a Parquet row:
   read that row) or fail the page with a clear error; never return the wrong bytes.
4. `ImageFilesWriter` rewrites `page.image.uri` and `extra`, which its contract does not declare.
5. `RegionRecognizer` replaces the transcription's earlier lines but declares `lines` as added.
6. `RegionRecognizer` ignores an explicit `pad` when the adapter has a `region_pad`: an explicit argument should
   win; the adapter's value is the default.

Fixes 2, 4 and 5 change contracts (and thus `pipeline_sha256` only if contracts are hashed: check; the squiddle
recipe's locked pipeline hash must not change). Fix 6 changes behavior only for callers who pass `pad` explicitly.

## Checks (lean)

The full suite once at the end; the goldens compare once (the engines change imports); each engine's tests once
in its environment; the CI command list once locally; the spike once.
