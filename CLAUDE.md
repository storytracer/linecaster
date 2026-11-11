# CLAUDE.md

Rules for working on linecaster, each with its reason. What linecaster is and how it works is in `docs/reference/`:
[architecture](docs/reference/architecture.md), [pipelines](docs/reference/pipelines.md),
[catalog](docs/reference/catalog.md), [data model](docs/reference/data-model.md),
[serialization](docs/reference/serialization.md), [tracing](docs/reference/tracing.md), [HTTP](docs/reference/http.md),
[compatibility](docs/reference/compatibility.md), with the [glossary](docs/reference/glossary.md) and the
[conventions](docs/reference/conventions.md). Measurements and decisions are in `NOTES.md`, changes in
`CHANGELOG.md`.

## Scope

- **linecaster is a generalist tool: it never depends on a specific collection, site, institution or project.** It
  is built on protocols (HTTP, S3/fsspec, OAI-PMH, IIIF), formats (ALTO, PAGE-XML, hOCR, Parquet, JSON Lines) and
  standards (METS/MODS, Unicode). Project-specific code, defaults and names belong in derivatives, and no project,
  collection, institution or machine is named in the repository (code, docs, catalog, tests, NOTES.md,
  CHANGELOG.md); examples use `example.org`, tests `library.test` and `example.org`. A project's choices would
  otherwise become everyone's defaults.
- **Everything that produces text from images lives here**; evaluations and project pipelines (derivatives) build
  on linecaster, never the other way round. One direction of dependency keeps linecaster usable by all of them.
- **No project chains in linecaster.** It ships blocks, backends, the data model, the run layout, the job helpers
  and pipeline-building helpers; example pipelines only as pipeline scripts (`pipelines/`), recipes as catalog
  entries, and in `tests/`. A recipe's name is neutral (`squiddle`); a derivative may be named after it, and its
  pipeline lives in its own repository.
- **Generic readers only**: folders, buckets, HF datasets, and the standards for items' manifests (IIIF
  Presentation, METS/MODS, also via OAI-PMH), which linecaster parses itself (`linecaster.formats.manifests`), and
  http(s) through its own HTTP layer (`linecaster.net`). Corpus or institution adapters belong in derivatives.
  Standards outlive institutions' APIs.
- **linecaster is not a data repository**: the catalog holds no evidence records and the docs quote no
  measurements. linecaster keeps the evidence format and the tooling that produces evidence, evaluations and
  ground-truth datasets ([catalog](docs/reference/catalog.md#measurements-live-elsewhere)); the records live with the
  evaluation that made them, and linecaster's own measurements and decisions in NOTES.md.

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

- **datatrove and saturate are the integration and required dependencies**: `datatrove[io,s3]>=0.10.1,<0.11` (it has
  `JobsPipelineExecutor`; its `s3` extra is s3fs, so `s3://` paths need no extra of linecaster's) and `saturate==0.3.0` (0.x changes without deprecation). linecaster adds only what they
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
- **The User-Agent stays datatrove's, `HF-Research/1.0`, deliberately** (`linecaster.net.http.USER_AGENT`, the
  default of every request; `--user-agent` and an HTTP policy's `user_agent` override it). datatrove is integral to
  linecaster, and its media fetcher (`HTTPFetchReader`) sends this User-Agent: a run that fetches with both then
  presents itself as one client to every host.
- **Only `linecaster-kraken` pins torch (`torch==2.14.0`), and only environments with it are bound by the pin**;
  the core never depends on torch, and other engines take what their own dependencies allow
  ([architecture](docs/reference/architecture.md#pipeline-scripts), `tests/test_scripts.py`). 2.14 is kraken's upper
  bound, and the PyPI 2.14 wheels are the CUDA 13 build on Linux (aarch64 and x86_64), which Blackwell GPUs need.
- **torch never changes as a side effect of a resolve** (a new dependency with its own torch bound, another package
  index, `uv run --with` on Jobs) in any environment: a change of build is deliberate, applies to one named
  environment, updates `TORCH` in `tests/test_scripts.py` and is recorded in NOTES.md. Another build moves numerics.
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
  sources, locks and wheels for both architectures (aarch64 and x86_64). uv's `required-environments` does not work
  in scripts, so the test does it.
- **A script lists only what it needs itself, with a comment saying why; a source is declared by the package that
  needs it** (the kraken fork by linecaster-kraken, the OpenCV stub by linecaster-paddlex;
  `tests/test_scripts.py`). `uv lock` applies the sources of path and git dependencies too; only `uv run --with`
  ignores them, and `jobs.dependencies` takes them from the script's lock. A source then has one place, and a script
  names no package only to carry its source.
- **Every pipeline script installs `linecaster[ray]`**: `--on ray` and `ray start` run the script's own environment on
  every node (a Job leaves Ray out). PEP 723 has no includes, so what every pipeline needs is one linecaster
  requirement with extras per script, not a shared file.
- **Pipeline scripts depend on no model choice; recipes bring their own environments.**
  `pipelines/transcribe_modular.py` has PaddleX and Tesseract, not kraken. Each catalog recipe has a script
  `recipes/<id>.py` with exactly the engine packages its presets need (`tests/test_scripts.py` derives them from the
  catalog) and a body that only calls `run.recipe(__file__, "<id>")`; the recipe itself stays YAML in the catalog.
  kraken's torch pin then binds only the environments that chose kraken (`recipes/squiddle.py`, the engine tests).
- **Recipe scripts take linecaster from its `main` branch on GitHub** (git sources, `branch = "main"`), so
  `uv run <raw URL of recipes/<id>.py> IN OUT` works with no checkout, as from one. They run what is pushed, not the
  working tree: develop and test unreleased code through `pipelines/` and pytest. After pushing changes a recipe
  needs, relock its script with `--upgrade-package` for linecaster's packages (`linecaster`, `linecaster-kraken`,
  `linecaster-paddlex`, `opencv-contrib-python`), which moves only their commit.
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
- **No measurements in the catalog or the docs; a measurement elsewhere is an evidence record with its source, and a
  claim is never a measurement.** linecaster is not a data repository, and a number that is not shipped cannot go
  stale.

## Determinism

- **One page per request; batching only within a page.** A page's result then depends only on the page, never on
  what else is in flight.

## Machines

- **Validate on both architectures: an aarch64 and an x86_64 machine with NVIDIA GPUs and CUDA 13** (for example a
  Blackwell GB10 and an Ada-generation card, the generation of HF Jobs' L4). No macOS for now. Both architectures run
  in production, and the locks and wheels must hold on both.

## Hugging Face Jobs

- **The namespace and bucket agreed with the maintainer (a spending cap agreed per session; report the cost of every
  run), flavor `l4x1`, outputs and datatrove's `logging_dir` in that bucket.** `--namespace` has no default.
  Spending stays visible and outputs in one place.
- **Always a small smoke job before a full run.** A mistake then costs minutes, not a full run.
- **The launching machine and the Jobs run the same Python minor version (3.12).** datatrove's experimental
  `JobsPipelineExecutor` dill-pickles the pipeline.
- **A Job's dependencies come from `linecaster.runtime.jobs.dependencies(commit, script)`, and the commit must be
  pushed.** `uv run --with` drops `[tool.uv.sources]`, so it spells out the script's sources and, from its lock, those
  of the packages it installs; it pins every other package at the lock's version, and the Job runs a uv script that
  carries the pins and the overrides (`uv run --with` ignores both). A Job then resolves what the lock holds.
- **No credential is stored in a pipeline or a repository.** Pipelines are pickled and recorded.

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

## Releases

- **The agent decides and makes the releases, by
  [versions and releases](docs/reference/compatibility.md#versions-and-releases)**, and patches are the rule: fixes,
  features that keep behavior and docs are patches, at the end of each finished piece of work, merged and green.
  Derivatives and the engine ranges rely on the version saying what changed.
- **Breaking changes wait on a branch and go out together as one minor** when a coherent piece of work is finished
  or the maintainer asks; `main` carries only patch-level changes. A minor names in its upgrade notes what users must
  change. The version should move slowly.
- **Never 1.0.0 without the maintainer's word.** It is a promise of deprecation periods.

## Working style

- **Small commits with plain messages.** They are easy to review and to revert.
- **Record measurements and anything that cannot be validated on the machines at hand in NOTES.md instead of
  guessing**, describing hardware generically (an aarch64 machine with a GB10 GPU), never by a machine's name. A
  guess written down looks like a fact later.
- **This repository is public: no costs, credentials, private dataset revisions or contents, personal data or machine
  addresses in files or commit messages.** Everything committed is published.
