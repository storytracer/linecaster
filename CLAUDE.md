# CLAUDE.md

Rules for working on linecaster, each with its reason. What linecaster is and how it works is in `docs/reference/`:
[architecture](docs/reference/architecture.md), [pipelines](docs/reference/pipelines.md),
[catalog](docs/reference/catalog.md), [data model](docs/reference/data-model.md),
[serialization](docs/reference/serialization.md), [tracing](docs/reference/tracing.md),
[compatibility](docs/reference/compatibility.md), with the [glossary](docs/reference/glossary.md) and the
[conventions](docs/reference/conventions.md). Measurements and decisions are in `NOTES.md`, changes in
`CHANGELOG.md`.

## Scope

- **Everything that produces text from images lives here**; evaluation (ocrscout, bhl-ocr-eval) and project
  pipelines (EBDC, FineBooks) build on linecaster, never the other way round. One direction of dependency keeps
  linecaster usable by all of them.
- **No project chains in linecaster.** It ships blocks, backends, the data model, the run layout, the job helpers
  and pipeline-building helpers; example pipelines only as pipeline scripts (`pipelines/`), recipes as catalog
  entries, and in `tests/`. The EBDC chain lives in `bookcommons/ebdc-pilot-pipeline`, the squiddle pipeline in
  `storytracer/squiddleocr`, the BHL re-OCR in `finebooks/bhl-commonpile-pipeline`. A project's choices would
  otherwise become everyone's defaults.
- **Generic readers only**: folders, buckets, HF datasets, and the standards for items' manifests (IIIF
  Presentation, METS/MODS, also via OAI-PMH, parsed by storytracer/pybookget). Corpus or institution adapters (BHL,
  GRIN, Europeana, e-rara) belong in derivatives, and pybookget's own handlers stay there. Standards outlive
  institutions' APIs.

## Terms and conventions

- **Use the glossary's terms and no others; add a term there before using it.** A *block* is a datatrove
  `PipelineStep`, a *pipeline* a list of blocks, and *executor*, *job*, *task*, *shard*, *worker* mean what they
  mean in datatrove; never call a linecaster concept a "module". One word with one meaning is what keeps the code,
  the docs and the derivatives readable together.
- **Follow the conventions** (names, American spelling, YAML and Markdown, contracts, docstrings, tracing,
  logging, errors, secrets). They are what makes names guessable and pipelines checkable.
- **Data model classes are plain nouns** (`Item`, `Page`, `PageImage`, `Transcription`, `Text`): no "Class"
  suffixes, and never `Document`. `Document` is datatrove's.

## Dependencies

- **datatrove and saturate are the integration and required dependencies**: `datatrove[io]>=0.10.1,<0.11` (it has
  `JobsPipelineExecutor`) and `saturate==0.3.0` (0.x changes without deprecation). linecaster adds only what they
  lack.
- **The data model, the formats, the text transforms, the image helpers and the built-in engines**
  (`linecaster.data`, `linecaster.formats`, `linecaster.text`, `linecaster.images`, `linecaster.engines`) **import
  neither datatrove nor saturate, nor linecaster's blocks or runtime** (`tests/test_import_rule.py`). Derivatives
  use them without the pipeline machinery.
- **A light core**: no kraken, torch, PaddlePaddle, ONNX Runtime or vLLM in the core, not even as an extra, and no
  LiteLLM anywhere. The one exception to few core dependencies is OpenTelemetry (`opentelemetry-api`, `-sdk`,
  `-exporter-otlp-proto-http`, with protobuf), required because tracing is always on. Engines bring their own
  stacks, whose pins conflict.
- **Extras only for genuinely optional things, each named after the one dependency it brings**; no umbrella or alias
  extras. Tools for working on linecaster are dependency groups (`dev`, `docs`), not extras. An extra then says
  exactly what it installs.
- **I/O through datatrove**: one datatrove `Document` per page; datatrove's readers, writers, `DataFolder` (fsspec)
  and executors for everything. Every executor and storage datatrove supports then works.
- **torch never changes as a side effect of a resolve** (a new dependency with its own torch bound, another package
  index, `uv run --with` on Jobs): a change of build is deliberate, applies to one named environment and is recorded
  in NOTES.md, and parity is then compared at CER level, not against the goldens. The PyPI 2.14 wheels are the CUDA
  13 build on Linux (aarch64 and x86_64), which the GB10 needs, and 2.14 is kraken's upper bound; another build moves
  numerics.
- **Python 3.12 (`requires-python >=3.12`) and uv ≥ 0.13.6 (`[tool.uv] required-version`) on every machine.** All
  machines then read the same locks.

## Pipeline scripts

- **No environment folders: a pipeline is a self-contained uv script** (`pipelines/`, a PEP 723 block, a
  `<script>.py.lock` next to it), **one per pipeline shape, never one per machine.** The machine is the executor's
  business (`--on`), not the pipeline's.
- **A pipeline script holds no pipeline code: it runs the pipeline shape of its name (`linecaster.pipelines.<name>`)**
  (`tests/test_scripts.py`). Derivatives' scripts then run the same shapes, and tests and the docs build them without
  the scripts' environments.
- **After changing a script's metadata: `uv lock --script <script>`**; `tests/test_scripts.py` checks pins,
  sources, locks and wheels for both machines. uv's `required-environments` does not work in scripts, so the test
  does it.
- **Scripts with kraken list the fork directly, and the numerically relevant versions are pinned with
  `constraint-dependencies`, the same list in every engine script.** Sources apply only to a script's direct
  dependencies, and every script must compute the same numbers.
- **The repository is not a uv workspace.** Engine pins conflict.
- **No default presets**: every slot is picked or filled by a recipe. A run then names exactly what it ran.

## Models and the catalog

- **kraken's models always come from their pinned Hugging Face mirrors**
  (`small-models-for-glam/kraken-ppocrv6-{tiny,small,medium}`, revisions and hashes in their model entries), never
  from Zenodo; the Zenodo DOIs are provenance, in each pin's `doi`. Zenodo throttles.
- **PaddleX's official models are its `PaddlePaddle/<name>_onnx` / `_safetensors` repositories, pinned in the
  catalog; new models with `linecaster catalog pin`.** Engines load exactly the pin.
- **Released editions never change** (`linecaster catalog verify` stays OK): a change that can change outputs is a
  new edition; a change that keeps behavior is a catalog migration, which keeps the old hash as `previous_sha256`.
  Run records name an edition and its hash, and must keep resolving.
- **Measurements are evidence records with their source; claims are never measurements.** Every number in the docs
  can then be traced.

## Determinism and parity

- **One page per request; batching only within a page.** A page's result then depends only on the page, never on
  what else is in flight.
- **squiddleocr's outputs (`~/data/goldens/squiddleocr-<sha>/<machine>/`) are the reference for the squiddle
  combination**: `tests/parity/compare_goldens.py RUN GOLDENS` compares page records with the golden hOCR line by
  line (line box, text, every word box), in-process and served. The modular pipeline must keep reproducing them.
- **Goldens are per machine; across machines compare at CER level, never byte for byte. A change that moves numerics
  (torch build, ONNX Runtime, decoding) is compared at CER level and recorded in NOTES.md.** GPU numerics differ.

## Machines

- **Validate on both machines**: spark (DGX Spark, GB10, aarch64, CUDA 13; the main development machine, goldens
  recorded here) and forge (RTX 4000 SFF Ada 20 GB, x86_64, CUDA 13.4; the x86 validation machine, same GPU
  generation as HF Jobs' L4, with its own goldens). No macOS for now. Both architectures run in production.

## Hugging Face Jobs

- **Namespace `finebooks` (cap agreed per session; report the cost of every run), flavor `l4x1`, outputs and
  datatrove's `logging_dir` in the bucket `hf://buckets/finebooks/linecaster-runs`.** Spending stays visible and
  outputs in one place.
- **Always a small smoke job before a full run.** A mistake then costs minutes, not a full run.
- **The launching machine and the Jobs run the same Python minor version (3.12).** datatrove's experimental
  `JobsPipelineExecutor` dill-pickles the pipeline.
- **A Job's dependencies come from `linecaster.runtime.jobs.dependencies(commit, script)`, and the commit must be
  pushed.** `uv run --with` drops `[tool.uv.sources]`.
- **Private derivatives ship their code as a wheel mounted from a bucket folder (`WheelJobsExecutor`,
  `wheel_volume`); no credential is stored in a pipeline or a repository.** Pipelines are pickled and recorded.

## Docs

- **Generated docs are written by `linecaster docs` at build time, never by hand and never committed**: the
  catalog's and the blocks' pages, `docs/index.md`, `docs/changelog.md` and `docs/llms*.txt` (git ignores them; CI
  and the docs workflow run it before building the site). Run `linecaster docs` before `mkdocs serve` to preview.
  Committed files outside `docs/` link to generated pages on the site (`latest`), never by relative path. The
  reference then cannot drift from the code, and no commit carries a regenerated page.
- **Reference docs (`docs/reference/`) describe what is, without history**; history belongs in `CHANGELOG.md` (with
  upgrade notes first) and NOTES.md. A reader needs the current state, and git keeps the rest.
- **Breaking changes follow the [compatibility](docs/reference/compatibility.md) statement**: while the version is
  0.x, no aliases, an upgrade note each. Derivatives pin linecaster and need to know what to change.

## Working style

- **Small commits with plain messages.** They are easy to review and to revert.
- **Record measurements and anything that cannot be validated on these machines in NOTES.md instead of guessing.**
  A guess written down looks like a fact later.
- **This repository is public: no costs, credentials, private dataset revisions or contents, personal data or machine
  addresses in files or commit messages.** Everything committed is published.
