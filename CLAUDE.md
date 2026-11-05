# CLAUDE.md

Guidance for working on linecaster. Status: first version built (November 2026): data model and
serializers, blocks, `linecaster serve`, kraken and PaddleX engines, HF Jobs pipelines; the squiddle
combination reproduces squiddleocr's goldens line for line. Measurements and decisions in NOTES.md;
the reference in `docs/reference/` (with the glossary and the conventions).

## What this is

An open, modular text-recognition suite for print and handwriting (OCR and HTR, old and new
documents). It combines layout, line, text, table and formula recognizers with post-processing
(dehyphenation, recomposition, normalization) into reproducible datatrove pipelines that turn page images
into text: the text as written, readable variants next to it, ALTO, PAGE-XML and hOCR on request.
Everything that produces text from images lives here; evaluation (ocrscout, bhl-ocr-eval) and
project pipelines (EBDC, FineBooks) are built on top of it, never the other way round.

## The rules

- **datatrove's terms and machinery.** A *block* is a datatrove `PipelineStep`; a *pipeline* is a
  list of blocks; *executor*, *job*, *task*, *shard*, *worker* as in datatrove. Never call a
  linecaster concept a "module". The only new term is **backend**: where a block's engine runs (in
  the pipeline's process, or behind a server reached through saturate).
- **datatrove + saturate are the integration** and required dependencies. Pins:
  `datatrove[io]>=0.10.1,<0.11` (has `JobsPipelineExecutor`), `saturate==0.3.0` (0.x changes without
  deprecation). Importing the data model, the formats, the text transforms and the image helpers
  (`linecaster.data`, `linecaster.formats`, `linecaster.text`, `linecaster.images`) must not import either, nor
  linecaster's blocks or runtime (`tests/test_import_rule.py`). Extras only for genuinely optional things, each named
  after the one dependency it brings; no umbrella or alias extras.
- **I/O through datatrove.** One datatrove `Document` per page; datatrove's readers, writers,
  `DataFolder` (fsspec) and executors for everything. linecaster only adds what datatrove lacks.
- **Generic readers only.** Folders, buckets, HF datasets, and the standards for items' manifests
  (IIIF Presentation, METS/MODS, also via OAI-PMH): `blocks/readers/manifests.py`, parsed by
  storytracer/pybookget (`read_manifest`), extra `[pybookget]`, which also fetches `http(s)://`
  images (`net/http.py`). A manifest lists an item's pages and their files. Corpus or institution
  adapters (BHL, GRIN, Europeana, e-rara) belong in derivatives (pybookget's own handlers stay there).
- **A light core.** No kraken, torch, PaddlePaddle, ONNX Runtime or vLLM in the core, not even as
  an extra. No LiteLLM anywhere. The one exception to keeping the core's dependencies few is OpenTelemetry
  (`opentelemetry-api`, `-sdk`, `-exporter-otlp-proto-http`, with protobuf): tracing is always on
  (`linecaster.tracing`), so it is a required dependency, not an extra.
- **No project chains in linecaster.** It ships blocks, backends, the data model, the run layout,
  the job helpers and pipeline-building helpers; example pipelines only as pipeline
  scripts (`pipelines/`), recipes as catalog entries, and in `tests/`. The EBDC chain lives in `bookcommons/ebdc-pilot-pipeline`, the "squiddle"
  pipeline in `storytracer/squiddleocr`, the BHL re-OCR in `finebooks/bhl-commonpile-pipeline`.

## Architecture: servers host models, the pipeline puts the steps together

- **Model blocks** (`ModelBlock` in `blocks/base/`: `LayoutDetector`, `LineDetector`, `LineRecognizer`,
  `TableRecognizer`, `FormulaRecognizer`, in their families under `blocks/`) each have a backend (`backends`): `InProcess("pkg:Class", **kwargs)` loads the engine in the
  worker (in `warm_up()`, before the first page; never pickled), `Served(endpoint, model=name)` streams pages through saturate
  (`AdaptiveClient` + `through()`: a window of pages in flight adapted to the server's queue gauges
  and 429s; results passed on as they finish; secrets as `EnvVar`). In-process is always available and is the parity
  reference. A page that failed a step (an exception in-process, a failed request served) carries
  `doc.metadata["errors"]`, bypasses later model steps at once (`skip_on_error`) and goes to `rejects/`; more
  failures than the error budget (`--max-page-errors`) fail the task. Library code raises `linecaster.errors`,
  never `SystemExit`.
- **`linecaster serve`** hosts engines: stateless (no state between requests), one worker per
  model (several replicas per model were measured at +7–10 % and removed; NOTES.md) with a bounded
  queue (`--max-queue`, 429 with `Retry-After` when full), routes `POST /v1/linecaster/{step}`
  (image + the transcription so far → the transcription with its part added), `GET /v1/models`,
  `/health` and vLLM-shaped `/metrics` (the gauges saturate reads).
- **VLMs** behind OpenAI-compatible servers (vLLM, SGLang, hosted endpoints): `PageRecognizer` /
  `RegionRecognizer` (`blocks/recognition/chat.py`) with `chat_model(<preset>)`: a catalog preset (engine `chat.v1`,
  data: revision, prompt, sampling, serve block) plus an adapter in `linecaster.adapters.ADAPTERS` (code:
  request, parsing); on `/v1/chat/completions`; served only.
- **The catalog** (`docs/reference/catalog.md`, `linecaster.catalog`): one catalog, `src/linecaster/catalog/data/`
  (engine packages and derivatives ship none): every entry is a YAML file (its JSON Schema, generated from the
  Pydantic models into `catalog/schemas/`, named in its first line; read with `ruamel.yaml` through
  `catalog.yamlio`) with its prose in a Markdown file next to it; every model is a model entry
  (`models/<id>/model.yaml`) with its
  upstream card copied verbatim at the pinned revision (always, whatever the license), every configuration
  a preset (`presets/<step>/<id>.yaml`, `id@edition`; steps `layout`, `lines`, `recognition`, `tables`,
  `formulas`, a VLM reading whole pages is `recognition` with `unit: page`, and the rule-based steps `image`,
  `normalization`, `typography`, `recomposition`, `composition`, whose engines are built in (`linecaster.engines`,
  in-process only, each declaring the scripts it covers; a preset's `by_script` maps scripts to strategies); it names its engine by versioned id, `engine:
  kraken.recognition.v1`, with `options` beside it, no "kind"; `version`/`revision` are upstream's, `edition`
  ours), released editions frozen in
  `catalog.lock` (`linecaster.lock/2`: an edition's hash covers its YAML; a catalog migration that keeps
  behavior recomputes it and keeps the old one as `previous_sha256`), measurements as evidence records with their source. Engines with weights load exactly the
  pin (`weights`, `catalog.fetch`). Page files and `OUT/run.yaml` record preset, edition and hash.
- **One page per request; batching only within a page** (kraken batches a page's lines). A page's
  result depends only on the page, never on what else is in flight, so runs are deterministic.
- **Servers inside a task** (one GPU per HF Job): `ModelServer` (`linecaster serve`) and
  `ChatModelServer` (vLLM) start the server through saturate's `Engine` and go **last** in the
  pipeline, after the writer: datatrove chains generators, and only the last one lives until every
  page is written.
- **Engines** live in `engines/<engine>/` (`linecaster-kraken`, `linecaster-paddlex`, `linecaster-tesseract`),
  each its own package; an engine is a class (`<Provider><Step>Engine`) with `engine_id` (its versioned id, the
  entry point's name in `linecaster.engines`), `step`, `capabilities` (unit, produces), an `Options` model (its
  keyword arguments; a preset's `weights` besides), `load()` and `__call__(image, transcription, **params) ->
  Transcription` (the page image as an RGB array and the transcription so far, returned with its part added). **No environment
  folders: a pipeline is a self-contained uv script** (`pipelines/`) (PEP 723 block, a `<script>.py.lock` next to it,
  `uv run <script>`) that builds one pipeline shape with slots, and **one pipeline script per shape,
  never one per machine**: `linecaster.runtime.run.main` gives every pipeline the same command line (`--on local|ray|hf-jobs`,
  `--backend in-process|served`, `--endpoint`, `serve` for `linecaster serve` with its models, `ray`
  for Ray's CLI from its environment). `pipelines/transcribe_modular.py` (lines and a recognizer, optionally layout,
  tables, formulas, then post-processing; every step a preset the user picks, no defaults) and `pipelines/transcribe_vlm.py` (a VLM per page or per
  region). **No default presets**: every slot is picked, or filled by a **recipe** (`--recipe`): a catalog
  entry naming a pipeline id (`transcribe_modular.v1`, the script's `PIPELINE`), a preset edition per slot and options,
  edition-frozen like presets, with whole-run evidence (squiddleocr's `squiddle` lives in linecaster's
  catalog). `uv run launch.py NAME IMAGES OUT` launches a recipe or a page preset by name: it finds the
  script whose `PIPELINE` the recipe names (page presets: `transcribe_vlm.v1`) and runs it (`uv run --script`) with
  `--recipe` / `--recognition`, so nobody needs to know the pipeline; own combinations use the pipeline scripts. Generated docs: `linecaster catalog docs --out docs/catalog --readme README.md`, one folder per
  kind (engines, models, presets, pipelines, recipes). `ModelServer(script=...)` starts a
  pipeline's `serve` with `uv run --script`;
  `linecaster.runtime.jobs.dependencies(commit, script)` turns its metadata into a Job's `--with` list
  (`ENGINE_SCRIPT` for the modular pipeline's engines). `OUT/run.yaml` records every block's `to_dict()` and
  `pipeline_sha256` (functional parameters only); a run into an OUT of another pipeline or `--tasks` is refused.
  Not a uv workspace, because engine pins conflict. Sources apply only to a script's direct
  dependencies, so scripts with kraken list the fork directly; the numerically relevant versions
  are pinned with `constraint-dependencies`, the same list in every engine script;
  `tests/test_scripts.py` checks pins, sources, locks and wheels for both machines (uv's
  `required-environments` does not work in scripts). PaddleX's GUI OpenCV pin is satisfied by
  `stubs/opencv-contrib-python` (the headless build of the same version; one cv2). After changing
  a script's metadata: `uv lock --script <script>`.

## Data model and serialization (from the EBDC pilot architecture)

Classes: `Item` (any multi-page unit: book, issue, manuscript, file; key `item_id`), `Page` (the
page record with its image and named transcriptions: `ocr_new` from a linecaster run, every block's default,
`ocr_original`, `ground_truth`; `page_id = item_id + sequence`), `PageImage`,
`Transcription` (the pilot's PageOCR, renamed because it also holds HTR and ground truth; module
`linecaster.data`), `Text` (one per item and variant). No "Class" suffixes; never
`Document`, which clashes with datatrove.

`Transcription` has `regions` (the layout contract between steps), `lines` (Line: id, region_id,
reading_order, row, bbox, polygon, baseline, score, text, normalized, confidence, alternatives, words, extra;
Word: id, text, bbox, confidence, hyphen, alternatives, extra; `bbox` is optional for text-only
transcriptions), `paragraphs` (Paragraph: id, region_id, rows with their line ids and character spans,
text, normalized, continuations, decisions), `docling` (the docling-core `DoclingDocument`, nested as it is),
derived `text`, `objects`, `confidence`, plus `language`, `steps` (one `StepInfo` per step: step, name,
engine, preset, settings, measurements in the fixed vocabulary `linecaster.data.MEASUREMENTS`) and `source`.
Stored page records are `linecaster.page/2`; `PageRecordReader` reads older ones. Every bbox
is `[x, y, width, height]` in pixels of the received image; `Transcription.scaled(sx, sy)` moves it
to another image size. Out: JSON via `model_dump_json` (exact round-trip), `to_alto` / `to_page` /
`to_hocr` and in: `from_alto` / `from_page` / `from_hocr` (lxml, never kraken's serializer; semantic
round-trip: structure, text, geometry, confidences, ids, reading order; `linecaster.formats`,
`docs/reference/serialization.md`).
No glyph level: words are the finest level.

Text (`linecaster.text.variants`, block `ItemTexts`): era-neutral vocabulary, three independent dimensions:
character fidelity (as written, normalized, expanded, regularized), flow (as laid out, flowed),
scope (full page, body only). Each transform moves one step on one dimension; the as-written layer
is never overwritten. Named variants: `verbatim_txt` (as written, as laid out, full page; pages
joined with a form feed) and `readable_txt` / `readable_md` (normalized by the explicit mapping
table, flowed with dehyphenation, body only). All text is NFC; the mapping folds ſ, ligatures,
r rotunda and superscript e over a/o/u; æ, œ, ø, å and ß stay; **never NFKC**; spelling is never
modernized.

## Run layout, enrichment chain, rejects

Each page-level pipeline reads the previous folder (`PageRecordReader`: page records of linecaster's
writers, images fetched again by URI, `uri_map` for local copies) and writes complete page records
with one more part filled in (`PageJsonlWriter`, `PageParquetWriter`); files are bucketed by item id
(a whole item in one file; no joins); `originals/` is never modified; `processed/…/<pipeline>/`,
`rejects/` (`RejectWriter`, put before the first writer by the builder: key, field, error, raw value of every
page that carries errors; checks like `PageValidator` record why on the page) and
`logs/<pipeline>/…` (datatrove's completion markers, logs, stats). One job = one pipeline for one
batch on one executor; resume is datatrove's, per task, so tasks stay small. Readers follow datatrove's
conventions (`BaseDiskReader`: `data_folder`, `paths_file`, `glob_pattern`, `limit`/`skip` per task; files, or
Parquet files, distributed over tasks in turn): `ImageFolderReader` (image files), `ImageParquetReader` (an image
column: bytes, HF image struct or path), `ManifestReader` (IIIF or METS; a manifest, or a row of a Parquet item
table, is an entry like a file, so an item stays in one task; pages fetched ahead with pybookget, rate limits per
task; `existing_ocr` keeps a library's OCR as `ocr_original`). The usual sequence is harvest → transcribe → bind:
`pipelines/harvest.py` downloads images (OCR, manifests) once into item folders plus page records, the transcribe
pipelines read those with `--pages`, `pipelines/bind.py` makes item texts. An item's pages can land in different tasks; item-level steps are a
second stage over item shards (`--item-shards N` writes `OUT/pages/<shard>/<rank>`, `pipelines/bind.py` reads
whole shards), as datatrove's own multi-stage pipelines read per-bucket folders. Each task starts its own
servers.

## Images

The working format for converted images is lossless WebP at full resolution (`linecaster.images.convert`,
block `ImageConverter`: 8-bit sRGB, ICC applied, method 0, exact); lossy output is never produced.
Delivered images used as they are (e.g. an access derivative) stay as delivered. Size limit,
checked from the header before decoding: width and height ≤ 16,383 (WebP's hard limit) and
width × height ≤ 2 × `PIL.Image.MAX_IMAGE_PIXELS` (Pillow's error threshold, read at run time and
never changed); larger pages go to `rejects/`.

## Parity and goldens

squiddleocr's outputs (`~/data/goldens/squiddleocr-<sha>/<machine>/`) are the reference for the
squiddle combination: `tests/parity/compare_goldens.py RUN GOLDENS` compares page records with the
golden hOCR line by line (line box, text, every word box). Goldens are per machine (GPU numerics
differ: compare across machines at CER level, never byte for byte). Parity is checked in-process and
served; a change that moves numerics (torch build, ONNX Runtime, decoding) is compared at CER level
and recorded in NOTES.md.

## Models

kraken's models always come from their pinned Hugging Face mirrors, never from Zenodo (it
throttles): `small-models-for-glam/kraken-ppocrv6-{tiny,small,medium}`, revisions and hashes in their
model entries (`src/linecaster/catalog/data/models/kraken-ppocrv6-*`; the Zenodo DOIs are provenance,
in each pin's `doi`); `small-models-for-glam/kraken-blla-base` (the BLLA base model of September 2026)
is still pinned in `linecaster_kraken.models` (no engine uses it). PaddleX's official models are its
`PaddlePaddle/<name>_onnx` / `_safetensors` repositories, pinned in the catalog and loaded from
the pinned snapshot (`create_predictor(model_dir=...)`); new models: `linecaster catalog pin`.

## Environment and machines

- Python 3.12 (`requires-python >=3.12`), uv ≥ 0.13.6 (`[tool.uv] required-version`) on every
  machine, so all read the same locks.
- **spark**: DGX Spark, GB10, aarch64, CUDA 13. Main development machine; goldens recorded here.
- **forge**: RTX 4000 SFF Ada 20 GB, x86_64, CUDA 13.4. The x86 validation machine; same GPU
  generation as HF Jobs' L4; keeps its own goldens.
- No macOS in this phase.
- torch: the PyPI 2.14 wheels are the CUDA 13 build on Linux (aarch64 and x86_64), which the GB10
  needs; 2.14 is kraken's upper bound. torch never changes as a side effect of a resolve
  (a new dependency with its own torch bound, another package index, `uv run --with` on Jobs):
  a change of build is deliberate, applies to one named environment and is recorded in NOTES.md,
  and parity is then compared at CER level, not against the goldens.

## Hugging Face Jobs

Namespace `finebooks` (cap agreed per session; report the cost of every run), flavor `l4x1`,
outputs and datatrove `logging_dir` in the bucket `hf://buckets/finebooks/linecaster-runs`. Always
a small smoke job before a full run. datatrove's `JobsPipelineExecutor` is experimental and
dill-pickles the pipeline, so the launching machine and the Jobs must run the same Python minor
version (3.12). `uv run --with` drops `[tool.uv.sources]`: `linecaster.runtime.jobs.dependencies(commit, script)`
spells out a pipeline's dependencies, sources (as URLs; the commit must be pushed) and pins. Private derivatives ship their code as a wheel mounted from a bucket
folder (`WheelJobsExecutor`, `wheel_volume`); no credential is stored in a pipeline or a repo.

## Working style

Small commits with plain messages. Record measurements and anything that cannot be validated on
these machines in NOTES.md instead of guessing. This repository is public: no costs, credentials,
private dataset revisions or contents, personal data or machine addresses in files or commit
messages.
