# Changelog

All notable changes to linecaster. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
each release lists upgrade notes first, then additions, changes, deprecations, removals and fixes. Versions follow
the tags; the first is `v0.1.0`.

## Unreleased

### Upgrade notes

The refactoring in `docs/plan/refactoring.md` lands in phases; each phase's renames are listed here. There are no
compatibility aliases: old imports, flags and ids fail.

**Phase 1: layout and names**

- Packages: `linecaster.transcription`, `linecaster.page` → `linecaster.data` (data model) and `linecaster.formats`
  (ALTO, PAGE, hOCR; `formats.docling` was `linecaster.document`); `text.py`, `unicode.py`, `reflow.py`,
  `retyper.py` → `linecaster.text.variants`, `.unicode`, `.recomposition`, `.typography`; `images.py`, `plots.py` →
  `linecaster.images`; `run`, `jobs`, `ray_executor`, `provenance` → `linecaster.runtime.*` (`run.rows()` →
  `run.pages()`); `linecaster.models` → `linecaster.adapters`; `blocks/http.py` → `linecaster.net`; blocks by
  family under `linecaster.blocks.<family>` (old modules `filters`, `media`, `models`, `serve`, `texts`,
  `document`, `readers`, `writers` are gone); `specs/` → `docs/reference/`.
- Blocks: `PageStep` → `PageBlock`, `ModelStep` → `ModelBlock`, `WorkingImages` → `ImageConverter`, `AttachImage`
  → `ImageFetcher`, `LayoutStep` → `LayoutDetector`, `LinesStep` → `LineDetector`, `AssignLinesToRegions` →
  `LineAssigner`, `RecognitionStep` → `LineRecognizer`, `ChatRegionStep` → `RegionRecognizer`, `ChatPageStep` →
  `PageRecognizer`, `TablesStep` → `TableRecognizer`, `FormulasStep` → `FormulaRecognizer`, `NormalizeUnicode` →
  `UnicodeNormalizer`, `Typography` → `Typographer`, `ComposePage` → `Composer`, `ValidatePages` → `PageValidator`,
  `RejectSink` → `RejectWriter`, `RecipeStamp` → `RecipeStamper`, `ServeModels` → `ModelServer`, `ServeChatModel`
  → `ChatModelServer`, `PageRowReader` → `PageRecordReader`; writers: `PageFilesWriter` + `PageExportsWriter` →
  `PageFileWriter` (`text_fallback=False` is the old `PageExportsWriter`), `ItemExportsWriter` →
  `ItemDocumentWriter`, `ItemTextJsonlWriter` + `ItemTextFilesWriter` → `ItemTextWriter(format=...)`. Datatrove
  display names changed with them (stats and logs).
- Engines: `…Model` → `…Engine` (`KrakenRecognitionEngine`, `PaddleLayoutEngine`, ...); ids unchanged. Adapters:
  `ChatModel` → `ChatAdapter`, each VLM adapter `X` → `XAdapter`.
- Pipeline scripts: `transcribe_chain.py` → `transcribe_modular.py`; ids `chain.v1` → `transcribe_modular.v1`,
  `vlm.v1` → `transcribe_vlm.v1`, new `harvest.v1`, `bind.v1`.
- Flags: `--recognizer` → `--recognition`; `--vlm`, `--vlm-endpoint` → `--recognition`, `--recognition-endpoint`;
  `--texts` → `--item-texts`; `--exports DIR` → `--files DIR --formats md,txt,json --naming squiddleocr
  --furniture`; `--rows` → `--pages`.
- Stored output: the default transcription `ocr` → `ocr_new`; page records in `OUT/rows/` → `OUT/pages/`; item text
  fidelity `normalised` → `normalized`; typography measurement `levelled` → `leveled`. Page records written before
  phase 1 keep `ocr`; read them with `transcription="ocr"`.
- Catalog: no step `page` (page presets are step `recognition`, unit `page`, under `presets/recognition/`); entries
  are `<id>.yaml` with prose in `<id>.md`; YAML is read as YAML 1.2 with `ruamel.yaml` (replaces PyYAML); lock format
  `linecaster.lock/2`. Edition numbers are unchanged; 20 hashes were recomputed (the page presets and `squiddle@1`),
  so files stamped by a recipe carry the new hash; old hashes still resolve (`previous_sha256`).
- American spelling throughout (e.g. `normalize`, `NORMALIZE_MAP`, `quantize_confidence`, `COLORS`).

**Phase 2: contracts and the builder**

- Pipeline scripts check their pipeline before they launch: a pipeline whose contracts do not fit exits with code 2
  and lists every problem. Own blocks without a `contract()` pass unchecked.
- With `--tasks` over 1, a binder after the page blocks (`--item-texts`) cuts the run into two stages: page records
  in item shards (`OUT/pages/<shard>/`), then the item stage; their logs are `OUT/logs/pages/` and
  `OUT/logs/items/`. One stage logs to `OUT/logs/` as before.
- `--dry-run` prints the plan under `plan` and the Mermaid graph after the JSON.
- A page an in-process block fails on no longer fails the task: it carries the error (`doc.metadata["errors"]`:
  `block`, `step`, `preset`, `type`, `error`; served failures in the same shape, no longer `{step, error}`), later
  model blocks pass it on at once, and it is written to `OUT/rejects/<rank>.jsonl` and kept in the page records.
  More failures than `--max-page-errors` (1 % of a task's pages, counting at least 100) fail the task.
- `ImageConverter(output_folder, rejects_folder, ...)` → `ImageConverter(output_folder, ...)` and
  `PageValidator(rejects_folder, required, prefix)` → `PageValidator(required)`: they record why on the page and
  pass it on (no longer dropped); the `RejectWriter` (now a writer block, `RejectWriter(output_folder, prefix="")`,
  which the builder puts before the first writer of a run) writes the rejects. A derivative that used either adds
  a `RejectWriter` where it wants the file, or lets the builder add one.
- Library code raises `linecaster.errors` (`PipelineConfigError`, `CatalogError`, `PageError`, `ServerError`)
  instead of `SystemExit`, `ValueError`, `KeyError`, `RuntimeError` and `TypeError` for configuration, catalog,
  page and server errors (e.g. an unknown preset is a `CatalogError`, an unknown block option a
  `PipelineConfigError`); pipeline scripts raise `PipelineConfigError` from `pipeline()`.
- `runtime.jobs.dependencies(commit)` without a script raises; give the pipeline's script,
  `runtime.jobs.ENGINE_SCRIPT` (the modular pipeline's engines) or `engines=False` (linecaster alone).
- The run record's schema is `linecaster.run-record/1` (was `linecaster.run/1`): `pipeline` lists the stages with
  every block's `to_dict()` and contract (was a list of block entries; the separate `stages` is gone), and
  `pipeline_sha256` is new. A run into an OUT whose record has another `pipeline_sha256` (or none: a record from
  before) is refused unless `--new-pipeline`; another `--tasks` always is.
- Page records carry `schema: linecaster.page/1` in their row. Records without one (written before phase 1) are read
  with `ocr` as `ocr_new`, and a `pages/` folder without records is read from its sibling `rows/`: no
  `transcription="ocr"` needed any more.
- Engines load in `warm_up()` before the first page, not on it: a page's measured `seconds` no longer include
  loading; the load time is the block's `warm_up_seconds` stat. `ModelServer` and `ChatModelServer` start their
  servers in `warm_up()` (stat `warm_up_seconds`, was the `boot` time stat).
- `engine_spec(ref)` and `preset_models(models)` take `installed=True`; tests that replace `engine_spec` accept it.
- On HF Jobs the tasks log JSON lines (`LINECASTER_LOG_JSON=1`, `runtime.jobs.JobsExecutor`; the run record's
  executor is `JobsExecutor`).

### Added

- Block contracts (`contract()`, `Part`, `Contract`, `PARTS`), the builder (`linecaster.runtime.builder`: `build`,
  `Plan`, checks, branches with `when=`/`group=`, composites, stages, `run_pages`), observers
  (`linecaster.runtime.observers`), the composite `ModularTranscriber`, the error classes (`linecaster.errors`),
  partial runs (`--until`, `--after`, `--tap-after`), `--page IMAGE` and `linecaster page`;
  `docs/reference/pipelines.md`.
- `docs/reference/glossary.md` and `docs/reference/conventions.md`.
- `warm_up()` on every block and backend, with the observers' `on_warm_up(block, seconds)`; per-page failures,
  `RejectWriter` as a block, the error budget (`--max-page-errors`, `build(max_page_errors=...)`).
- `to_dict()` on every block, backend and chat adapter; the run record's pydantic model
  (`linecaster.runtime.record.RunRecord`, `schemas/run-record-1.json`); `provenance.functional_pipeline` and
  `pipeline_sha256`; `--new-pipeline`.
- The describe mode (`runtime.run.describe_script`, `describe_recipe`, `load_script`, `parse`); a recipe edition's
  expanded pipeline in the lock (`pipeline`, `pipeline_sha256`), checked by `catalog verify`; `catalog release
  --migrate-pipeline`. `squiddle@1` has its pipeline recorded.
- Secrets as references: `linecaster.runtime.secrets.EnvVar`; `Served(api_key=..., headers=...)`.
- `linecaster.runtime.logs` (JSON-lines task logs), `runtime.jobs.JobsExecutor`.
