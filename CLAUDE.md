# CLAUDE.md

Guidance for working on linecaster. Status: first version built (November 2026): data model and
serialisers, blocks, `linecaster serve`, kraken and PaddleX engines, HF Jobs recipes; the squiddle
combination reproduces squiddleocr's goldens line for line. Decisions and measurements in NOTES.md
and `specs/`.

## What this is

An open, modular text-recognition suite for print and handwriting (OCR and HTR, old and new
documents). It combines layout, line, text, table and formula recognisers with post-processing
(dehyphenation, reflow, normalisation) into reproducible datatrove pipelines that turn page images
into text: the text as written, readable variants next to it, ALTO, PAGE-XML and hOCR on request.
Everything that produces text from images lives here; evaluation (ocrscout, bhl-ocr-eval) and
project pipelines (EBDC, FineBooks) are built on top of it, never the other way round.

## The rules

- **datatrove's terms and machinery.** A *block* is a datatrove `PipelineStep`; a *pipeline* is a
  list of blocks; *executor*, *job*, *task*, *shard*, *worker* as in datatrove. Never call a
  linecaster concept a "module". The only new term is **backend**: where a block's model runs (in
  the pipeline's process, or behind a server reached through saturate).
- **datatrove + saturate are the integration** and required dependencies. Pins:
  `datatrove[io]>=0.10.1,<0.11` (has `JobsPipelineExecutor`), `saturate==0.3.0` (0.x changes without
  deprecation). Importing the data model, serialisers and text transforms (`linecaster.transcription`,
  `linecaster.text`) must not import either. Extras only for genuinely optional things, each named
  after the one dependency it brings; no umbrella or alias extras.
- **I/O through datatrove.** One datatrove `Document` per page; datatrove's readers, writers,
  `DataFolder` (fsspec) and executors for everything. linecaster only adds what datatrove lacks.
- **Generic connectors only.** Folders, buckets, HF datasets. Corpus or institution adapters
  (BHL, GRIN, Europeana, IIIF, METS) belong in derivatives.
- **A light core.** No kraken, torch, PaddlePaddle, ONNX Runtime or vLLM in the core, not even as
  an extra. No LiteLLM anywhere.
- **No project chains in linecaster.** It ships blocks, backends, the data model, the run layout,
  the job helpers and pipeline-assembly helpers; example pipelines only as recipes
  (`recipes/`) and in `tests/`. The EBDC chain lives in `bookcommons/ebdc-pilot-pipeline`, the "squiddle"
  pipeline in `storytracer/squiddleocr`, the BHL re-OCR in `finebooks/bhl-commonpile-pipeline`.

## Architecture: servers host models, the pipeline composes the chain

- **Model blocks** (`blocks/models.py`: `LayoutStep`, `LinesStep`, `RecognitionStep`, `TablesStep`)
  each have a backend (`backends`): `InProcess("pkg:Class", **kwargs)` loads the engine model in the
  worker (lazily; never pickled), `Served(endpoint, model=name)` streams pages through saturate
  (`AdaptiveClient` + `through()`: a window of pages in flight adapted to the server's queue gauges
  and 429s; results passed on as they finish). In-process is always available and is the parity
  reference. A page that failed a step carries `doc.metadata["errors"]` and bypasses later model
  steps (`skip_on_error`).
- **`linecaster serve`** hosts engine models: stateless (no state between requests), one worker per
  model (several replicas per model were measured at +7–10 % and removed; NOTES.md) with a bounded
  queue (`--max-queue`, 429 with `Retry-After` when full), routes `POST /v1/linecaster/{step}`
  (image + the transcription so far → the transcription with its part added), `GET /v1/models`,
  `/health` and vLLM-shaped `/metrics` (the gauges saturate reads).
- **VLMs** behind OpenAI-compatible servers (vLLM, SGLang, hosted endpoints): `ChatPageStep` /
  `ChatRegionStep` (`blocks/chat.py`) with `chat_model(<preset>)`: a catalogue preset (engine `chat/1`,
  data: revision, prompt, sampling, serve block) plus an adapter in `linecaster.models.ADAPTERS` (code:
  request, parsing); on `/v1/chat/completions`; served only.
- **The catalogue** (`specs/catalog.md`, `linecaster.catalog`): every model is a model document with its
  upstream card copied verbatim at the pinned revision (always, whatever the licence), every configuration
  a preset (`id@edition`; `version`/`revision` are upstream's, `edition` ours), released editions frozen in
  `catalog.lock`, measurements as evidence records with their source. Engines with weights load exactly the
  pin (`weights`, `catalog.fetch`). Page files and `OUT/run.yaml` record preset, edition and hash.
- **One page per request; batching only within a page** (kraken batches a page's lines). A page's
  result depends only on the page, never on what else is in flight, so runs are deterministic.
- **Servers inside a task** (one GPU per HF Job): `ServeModels` (`linecaster serve`) and
  `ServeChatModel` (vLLM) start the server through saturate's `Engine` and go **last** in the
  pipeline, after the writer: datatrove chains generators, and only the last one lives until every
  page is written.
- **Engines** live in `engines/<engine>/` (`linecaster-kraken`, `linecaster-paddlex`, `linecaster-tesseract`),
  each its own package; an engine model is a class with `step`, `name`, `load()` and
  `__call__(image, transcription, **params) -> Transcription`. **No environment
  folders: a recipe is a self-contained uv script** (PEP 723 block, a `<script>.py.lock` next to it,
  `uv run <script>`) that builds one pipeline, and **one recipe per pipeline, never one per
  machine**: `linecaster.run.main` gives every recipe the same command line (`--on local|ray|hf-jobs`,
  `--backend in-process|served`, `--endpoint`, `serve` for `linecaster serve` with its models, `ray`
  for Ray's CLI from its environment). `recipes/chain.py` (lines and a recogniser, optionally layout,
  tables, formulas, then post-processing; every step a preset the user picks, no defaults) and `recipes/vlm.py` (a VLM per page or per
  region). `ServeModels(script=...)` starts a recipe's `serve` with `uv run --script`;
  `linecaster.jobs.dependencies(commit, script)` turns its metadata into a Job's `--with` list.
  Not a uv workspace, because engine pins conflict. Sources apply only to a script's direct
  dependencies, so scripts with kraken list the fork directly; the numerically relevant versions
  are pinned with `constraint-dependencies`, the same list in every engine script;
  `tests/test_scripts.py` checks pins, sources, locks and wheels for both machines (uv's
  `required-environments` does not work in scripts). PaddleX's GUI OpenCV pin is satisfied by
  `stubs/opencv-contrib-python` (the headless build of the same version; one cv2). After changing
  a script's metadata: `uv lock --script <script>`.

## Data model and serialisation (from the EBDC pilot architecture)

Classes: `Item` (any multi-page unit: book, issue, manuscript, file; key `item_id`), `Page` (the
row with its image and named transcriptions; `page_id = item_id + sequence`), `PageImage`,
`Transcription` (the pilot's PageOCR, renamed because it also holds HTR and ground truth; module
`linecaster.transcription`), `Text` (one per item and variant). No "Class" suffixes; never
`Document`, which clashes with datatrove.

`Transcription` has `regions` (the layout contract between steps), `lines` (Line: id, region_id,
reading_order, row, bbox, polygon, baseline, score, text, confidence, alternatives, words, extra;
Word: id, text, bbox, confidence, hyphen, alternatives, extra; `bbox` is optional for text-only
transcriptions), `docling` (the docling-core `DoclingDocument`, nested as it is), derived `text`,
`objects`, `confidence`, plus `language`, `model` (one `ModelInfo` per step) and `source`. Every bbox
is `[x, y, width, height]` in pixels of the received image; `Transcription.scaled(sx, sy)` moves it
to another image size. Out: JSON via `model_dump_json` (exact round-trip), `to_alto` / `to_page` /
`to_hocr` and in: `from_alto` / `from_page` / `from_hocr` (lxml, never kraken's serialiser; semantic
round-trip: structure, text, geometry, confidences, ids, reading order; `specs/serialisation.md`).
No glyph level: words are the finest level.

Text (`linecaster.text`, block `ItemTexts`): era-neutral vocabulary, three independent dimensions:
character fidelity (as written, normalised, expanded, regularised), flow (as laid out, flowed),
scope (full page, body only). Each transform moves one step on one dimension; the as-written layer
is never overwritten. Named variants: `verbatim_txt` (as written, as laid out, full page; pages
joined with a form feed) and `readable_txt` / `readable_md` (normalised by the explicit mapping
table, flowed with dehyphenation, body only). All text is NFC; the mapping folds ſ, ligatures,
r rotunda and superscript e over a/o/u; æ, œ, ø, å and ß stay; **never NFKC**; spelling is never
modernised.

## Run layout, enrichment chain, rejects

Each page-level pipeline reads the previous folder (`PageRowReader`: page rows of linecaster's
writers, images fetched again by URI, `uri_map` for local copies) and writes complete page rows
with one more part filled in (`PageJsonlWriter`, `PageParquetWriter`); files are bucketed by item id
(a whole item in one file; no joins); `originals/` is never modified; `processed/…/<pipeline>/`,
`rejects/<output>/` (`RejectSink`: key, field, error, raw value; `ValidatePages`) and
`logs/<pipeline>/…` (datatrove's completion markers, logs, stats). One job = one pipeline for one
batch on one executor; resume is datatrove's, per task, so tasks stay small.

## Images

The working format for converted images is lossless WebP at full resolution (`linecaster.images`,
block `WorkingImages`: 8-bit sRGB, ICC applied, method 0, exact); lossy output is never produced.
Delivered images used as they are (e.g. an access derivative) stay as delivered. Size limit,
checked from the header before decoding: width and height ≤ 16,383 (WebP's hard limit) and
width × height ≤ 2 × `PIL.Image.MAX_IMAGE_PIXELS` (Pillow's error threshold, read at run time and
never changed); larger pages go to `rejects/`.

## Parity and goldens

squiddleocr's outputs (`~/data/goldens/squiddleocr-<sha>/<machine>/`) are the reference for the
squiddle combination: `tests/parity/compare_goldens.py RUN GOLDENS` compares page rows with the
golden hOCR line by line (line box, text, every word box). Goldens are per machine (GPU numerics
differ: compare across machines at CER level, never byte for byte). Parity is checked in-process and
served; a change that moves numerics (torch build, ONNX Runtime, decoding) is compared at CER level
and recorded in NOTES.md.

## Models

kraken's models always come from their pinned Hugging Face mirrors, never from Zenodo (it
throttles): `small-models-for-glam/kraken-ppocrv6-{tiny,small,medium}`, revisions and hashes in their
model documents (`engines/kraken/src/linecaster_kraken/catalog/models/`; the Zenodo DOIs are provenance,
in each pin's `doi`); `small-models-for-glam/kraken-blla-base` (the BLLA base model of September 2026)
is still pinned in `linecaster_kraken.models` (no engine uses it). PaddleX's official models are its
`PaddlePaddle/<name>_onnx` / `_safetensors` repositories, pinned in the paddlex catalogue and loaded from
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
version (3.12). `uv run --with` drops `[tool.uv.sources]`: `linecaster.jobs.dependencies(commit, script)`
spells out a recipe's dependencies, sources (as URLs; the commit must be pushed) and pins. Private derivatives ship their code as a wheel mounted from a bucket
folder (`WheelJobsExecutor`, `wheel_volume`); no credential is stored in a pipeline or a repo.

## Working style

Small commits with plain messages. Record measurements and anything that cannot be validated on
these machines in NOTES.md instead of guessing. This repository is public: no costs, credentials,
private dataset revisions or contents, personal data or machine addresses in files or commit
messages.
