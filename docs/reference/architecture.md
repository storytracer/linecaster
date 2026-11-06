# Architecture

What linecaster is made of and how a run fits together. Terms are the [glossary](glossary.md)'s; contracts, the
builder, failures and the run record are in [pipelines](pipelines.md), models, presets, recipes and engines in the
[catalog](catalog.md), the page record in the [data model](data-model.md).

## What linecaster is

An open, modular text-recognition suite for print and handwriting (OCR and HTR, old and new documents). It
combines layout, line, text, table and formula recognizers with post-processing (dehyphenation, recomposition,
normalization) into reproducible datatrove pipelines that turn page images into text: the text as written, readable
variants next to it, ALTO, PAGE-XML and hOCR on request. Everything that produces text from images lives here;
evaluation (ocrscout, bhl-ocr-eval) and project pipelines (EBDC, FineBooks) are built on top of it.

## Packages

| Package | Holds |
|---|---|
| `linecaster.data` | the data model: `Item`, `Page`, `PageImage`, `Transcription`, `Text`, `StepInfo`, the measurements vocabulary |
| `linecaster.formats` | ALTO, PAGE-XML and hOCR out and in; the DoclingDocument exports |
| `linecaster.text` | the text transforms: Unicode, typography, recomposition, the text variants |
| `linecaster.images` | the working image, plots |
| `linecaster.engines` | the built-in engines: the rule-based steps and the single-region layout |
| `linecaster.blocks` | the blocks by family ([blocks](../blocks/README.md)) |
| `linecaster.backends` | `InProcess`, `Served`, `Chat` |
| `linecaster.adapters` | one adapter per VLM family, `ADAPTERS` |
| `linecaster.serve` | `linecaster serve` |
| `linecaster.runtime` | the builder, the pipelines' command line, executors, the run record, Jobs helpers, secrets, logs |
| `linecaster.catalog` | the catalog: its entries, schemas, lock, fetching pins, the docs of its entries |
| `linecaster.tracing` | tracing (OpenTelemetry) and `linecaster traces` |
| `linecaster.docs` | `linecaster docs`: the generated pages |

The first five load neither datatrove nor saturate, nor linecaster's blocks or runtime (`tests/test_import_rule.py`),
so derivatives can use the data model and the formats without the pipeline machinery. datatrove and saturate are
required dependencies; engines, Ray, pybookget and PDFium are not (engine packages and extras).

## Blocks and backends

A block is a datatrove `PipelineStep` with a contract; a pipeline is a list of blocks run by a datatrove executor.
Each family is a subpackage of `linecaster.blocks` ([blocks](../blocks/README.md) has a page per block).

**Model blocks** (`ModelBlock`: `LayoutDetector`, `LineDetector`, `LineRecognizer`, `TableRecognizer`,
`FormulaRecognizer`, `PageRecognizer`, `RegionRecognizer`) each have a backend:

- `InProcess("pkg:Class", **kwargs)` (or a preset ref) loads the engine in the worker, in `warm_up()` before the
  first page; a loaded engine is never pickled. In-process is always available and is the parity reference.
- `Served(endpoint, model=name)` and `Chat(preset, endpoint)` (a VLM) stream pages through saturate
  (`AdaptiveClient` and `through()`): a window of pages in flight, adapted to the server's queue gauges and 429s;
  results passed on as they finish; secrets as `EnvVar`. The streaming exists once, in `ModelBlock`.

A page that failed a step carries `doc.metadata["errors"]`, passes later model steps at once and goes to
`rejects/`; more failures than the error budget fail the task ([pipelines](pipelines.md#failures)). Library code
raises `linecaster.errors`, never `SystemExit`.

**Rule blocks** (`RuleBlock`: `Typographer`, `Recomposer`, `Composer`, `CharacterNormalizer`; and `ImageConverter`)
run a built-in engine of a rule-based step in the pipeline's process, picked by a preset.

## One page per request

A request carries one page; engines batch only within a page (kraken batches a page's lines). A page's result
depends only on the page, never on what else is in flight, so runs are deterministic whatever the executor, the
number of tasks or the backend.

## Servers

- **`linecaster serve`** hosts engines: stateless (no state between requests), one worker per model (several
  replicas per model were measured at +7–10 % and removed; NOTES.md), each with a bounded queue (`--max-queue`; a
  full queue answers 429 with `Retry-After`). Routes: `POST /v1/linecaster/{step}` (the image and the transcription
  so far in, the transcription with its part added out), `GET /v1/models`, `/health` and vLLM-shaped `/metrics`
  (the gauges saturate reads). Built-in engines are not served: they run in the pipeline's process.
- **VLMs** run behind OpenAI-compatible servers (vLLM, SGLang, hosted endpoints): `PageRecognizer` and
  `RegionRecognizer` on the `Chat` backend, on `/v1/chat/completions`, served only. A VLM is a catalog preset
  (engine `chat.v1`; its data: revision, prompt, sampling, serve block) plus an adapter in
  `linecaster.adapters.ADAPTERS` (its code: the request, the parsing; `chat_model(<preset>)`).
- **Servers inside a task** (one GPU per HF Job): the server blocks `ModelServer` (`linecaster serve`) and
  `ChatModelServer` (vLLM or SGLang) start the server through saturate's `Engine` and go last in the pipeline,
  after the writer: datatrove chains generators, and only the last one lives until every page is written. Each
  task starts its own servers. `ModelServer(script=...)` starts a pipeline script's `serve` with
  `uv run --script`.

## Engines

An engine is a class with a versioned id ([catalog](catalog.md#engines)). Engine packages live in
`engines/<engine>/`, each its own package: `linecaster-kraken`, `linecaster-paddlex`, `linecaster-tesseract`. An
engine class (`<Provider><Step>Engine`) has `engine_id` (the entry point's name in `linecaster.engines`), `step`,
`capabilities` (unit, produces), an `Options` model (its keyword arguments; a preset's `weights` besides), `load()`
and `__call__(image, transcription, **params) -> Transcription` (the page image as an RGB array and the
transcription so far, returned with its part added). Engines with weights load exactly the pin (`weights`,
`linecaster.catalog.fetch`). PaddleX's models load from the pinned snapshot (`create_predictor(model_dir=...)`);
`small-models-for-glam/kraken-blla-base` (the BLLA base model of September 2026) is pinned in
`linecaster_kraken.models`, and no engine uses it. Engine packages carry code only; their presets and models are in
linecaster's catalog.

## Pipeline scripts

There are no environment folders: a pipeline is a self-contained uv script in `pipelines/` (a PEP 723 block, a
`<script>.py.lock` next to it, `uv run <script>`) that builds one pipeline shape with slots, one script per shape,
never one per machine:

| Script | Pipeline id | Does |
|---|---|---|
| `harvest.py` | `harvest.v1` | downloads page images (and a library's OCR, manifests) once into item folders, plus page records |
| `transcribe_modular.py` | `transcribe_modular.v1` | lines and a recognizer, optionally layout, tables, formulas, then post-processing; every step a preset the user picks |
| `transcribe_vlm.py` | `transcribe_vlm.v1` | a VLM per page or per layout region |
| `bind.py` | `bind.v1` | item texts and item documents from page records |

`linecaster.runtime.run.main` gives every pipeline the same command line: `--on local|ray|hf-jobs`, `--backend
in-process|served`, `--endpoint` (a running server), `serve` (`linecaster serve` with the script's models), `ray`
(Ray's CLI from the script's environment). Slots have no default presets: every slot is picked, or a recipe fills
them (`--recipe`); `launch.py` runs a recipe or a page preset by name ([catalog](catalog.md#pipelines-recipes-and-launchpy)).
Each script's page in the [catalog's docs](../catalog/README.md) lists its slots and options.

Script environments: the repository is not a uv workspace (engine pins conflict). Sources apply only to a script's
direct dependencies, so scripts with kraken list the fork directly; the numerically relevant versions are pinned with
`constraint-dependencies`, the same list in every engine script. `tests/test_scripts.py` checks pins, sources, locks
and wheels for both machines (uv's `required-environments` does not work in scripts). PaddleX's GUI OpenCV pin is
satisfied by `stubs/opencv-contrib-python` (the headless build of the same version; one cv2).

## Executors and Jobs

| `--on` | Executor |
|---|---|
| `local` | datatrove's `LocalPipelineExecutor` |
| `ray` | `RayGPUExecutor` for stages with servers (one task per GPU), datatrove's `RayPipelineExecutor` otherwise (extra `[ray]`) |
| `hf-jobs` | `JobsExecutor`: datatrove's `JobsPipelineExecutor` with JSON-lines logs; `GPUJobsExecutor` for multi-GPU flavors |

datatrove's `JobsPipelineExecutor` is experimental and dill-pickles the pipeline, so the launching machine and the
Jobs run the same Python minor version (3.12). `uv run --with` drops `[tool.uv.sources]`:
`linecaster.runtime.jobs.dependencies(commit, script)` spells out a pipeline's dependencies, sources (as URLs; the
commit must be pushed) and pins ([pipelines](pipelines.md#hf-jobs-helpers)). A private derivative ships its code as
a wheel mounted from a bucket folder (`WheelJobsExecutor`, `wheel_volume`).

## The run layout

One job is one pipeline for one batch on one executor; resume is datatrove's, per task, so tasks stay small. A
pipeline reads the previous folder and writes complete page records with one more part filled in:

| Folder | Holds |
|---|---|
| `originals/` | the delivered images and files; never modified |
| `OUT/pages/` | page records (`PageJsonlWriter`, `PageParquetWriter`), bucketed by item id: a whole item in one file, so no joins |
| `OUT/rejects/` | every page that carries errors (`RejectWriter`, put before the first writer by the builder): key, field, error, raw value |
| `OUT/logs/` | datatrove's completion markers, logs and stats |
| `OUT/traces/` | the traces ([tracing](tracing.md)) |
| `OUT/run.yaml` | the run record ([pipelines](pipelines.md#the-run-record)) |

`PageRecordReader` reads page records of linecaster's writers, fetching images again by URI (`uri_map` for local
copies). Checks like `PageValidator` record on the page why it failed.

**Readers** follow datatrove's conventions (`BaseDiskReader`: `data_folder`, `paths_file`, `glob_pattern`,
`limit`/`skip` per task; files, or Parquet files, distributed over tasks in turn): `ImageFolderReader` (image files),
`ImageParquetReader` (an image column: bytes, an HF image struct or a path), `ManifestReader` (IIIF or METS, parsed
by pybookget, extra `[pybookget]`, which also fetches `http(s)://` images through `linecaster.net.http`; a manifest,
or a row of a Parquet item table, is an entry like a file, so an item stays in one task; a IIIF Collection entry is
its manifests, one level; pages fetched ahead, rate limits per task; `existing_ocr` fetches a library's OCR as a
document media, which a `TranscriptionConverter` reads as `ocr_original`, the builder adding one when missing),
`PdfReader` (PDF files as items, pages rendered with pypdfium2, extra `[pypdfium2]`) and `PageRecordReader`.

**The workflow** is harvest → transcribe → bind: `pipelines/harvest.py` downloads images (and OCR, manifests) once
into item folders plus page records, the transcribe pipelines read those with `--pages`, `pipelines/bind.py` makes
item texts and documents. An item's pages can land in different tasks; item-level steps are a second stage over item
shards (`--item-shards N` writes `OUT/pages/<shard>/<rank>`, `pipelines/bind.py` reads whole shards), as datatrove's
own multi-stage pipelines read per-bucket folders ([pipelines](pipelines.md#the-item-stage)).
