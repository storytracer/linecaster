# CLAUDE.md

Guidance for working on linecaster. Status: skeleton only; the decisions below are settled and
the code is being built against them.

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
  linecaster concept a "module". The only new term is **backend**: where a block's model runs
  (in the pipeline's process, in a separate process with its own uv environment, or behind a
  server reached through saturate).
- **I/O through datatrove.** One datatrove `Document` per page; datatrove's readers, writers,
  `DataFolder` (fsspec) and executors for everything. linecaster only adds what datatrove lacks
  (a reader for plain image files, an HF image-dataset adapter, per-page file writers).
- **Generic connectors only.** Folders, buckets, HF datasets. Corpus or institution adapters
  (BHL, GRIN, Europeana, IIIF, METS) belong in derivatives.
- **A light core.** No kraken, torch, PaddlePaddle, ONNX Runtime or vLLM in the core, not even as
  an extra. Heavy engines live in `backends/<engine>/`, each its own uv project with its own lock;
  these are NOT a uv workspace, because their pins conflict. No LiteLLM anywhere.
- **Extras are named after the one dependency they bring:** `[datatrove]`, `[saturate]`; no
  umbrella or alias extras; combinations are written out.
- **No project chains in linecaster.** It ships blocks, backends, the data model, the run layout,
  the job contract and pipeline-assembly helpers; example pipelines only under `examples/` and
  `tests/`. The EBDC chain lives in `bookcommons/ebdc-pilot-pipeline`, the "squiddle" pipeline in
  `storytracer/squiddleocr`, the BHL re-OCR in `finebooks/bhl-commonpile-pipeline`.

## Data model and serialisation (from the EBDC pilot architecture)

Classes: `Item` (any multi-page unit: book, issue, manuscript, file; key `item_id`), `Page` (the
row with its image and transcriptions; `page_id = item_id + sequence`), `PageImage`,
`Transcription` (the pilot's PageOCR, renamed because it also holds HTR and ground truth; module
`linecaster.transcription`), `Text` (one per item and variant). No "Class" suffixes; never
`Document`, which clashes with datatrove.

`Transcription` follows the pilot deck's PageOCR slides exactly: two primary parts, `docling`
(the docling-core `DoclingDocument`, nested as it is: structure, reading order, body and furniture
layers, tables, formulas, provenance per item) and `lines` (Line: id, region_id, reading_order,
bbox, baseline, polygon, text, confidence, alternatives, words, extra; Word: id, text, bbox,
confidence, hyphen, alternatives, extra); derived fields `text`, `objects`, `confidence`,
`language`; plus `model` and `source`. Every bbox is `[x, y, width, height]` in pixels of the
received image. In: `from_alto`, `from_page`, `from_hocr` and native producers. Out: JSON via
`model_dump_json` (exact round-trip, published JSON Schema), `to_alto`, `to_page`, `to_hocr`
(semantic round-trip: structure, text, geometry, confidences, ids, reading order), Docling exports
(text, Markdown, DocLang, HTML; export only). No glyph level: words are the finest level, so a
backend that has character cuts (kraken) turns them into words itself. The XML formats are
implemented in the core on lxml, never through kraken's serialiser.

Output vocabulary is era-neutral, three independent dimensions: character fidelity (as written,
normalised, expanded, regularised), flow (as laid out, flowed), scope (full page, body only).
Each transform moves one step on one dimension and records it; the as-written layer is never
overwritten. The pilot's text variants are named points on them: `verbatim_txt` (as written, as
laid out, full page) and `readable_txt` / `readable_md` (normalised by an explicit mapping table,
flowed, body only). All text is NFC; the readable mapping folds ſ, ligatures, r rotunda and
superscript e; æ, œ, ø, å and ß stay; **never NFKC**; spelling is never modernised.

## Run layout and jobs

As in the pilot: each page-level pipeline reads the previous folder and writes complete page rows
with one more part filled in; files are bucketed by item id (a whole item in one file; no joins);
`originals/` is never modified; `processed/…/<pipeline>/`, `rejects/<output>/` (key, field, error,
raw value) and `logs/<pipeline>/…` (completion markers, logs, stats). One job = one pipeline for one
batch on one executor; resume is datatrove's, per task, so tasks stay small.

## Models

kraken's models always come from their pinned Hugging Face mirrors, never from Zenodo (it
throttles): `small-models-for-glam/kraken-ppocrv6-{tiny,small,medium}` and
`small-models-for-glam/kraken-blla-base` (the BLLA base model of September 2026); revisions and
hashes as pinned in squiddleocr's `models.KRAKEN_MODELS`. The Zenodo DOIs are provenance only.

## Environment and machines

- Python 3.12 (`requires-python >=3.12`), uv ≥ 0.13.6 (`[tool.uv] required-version`) on every
  machine, so all read the same `uv.lock`.
- **spark** (this machine; Tailscale name `dgx`): DGX Spark, GB10, aarch64, CUDA 13. Main
  development machine; golden outputs are recorded here.
- **forge** (`ssh forge`, over the tailnet): Hetzner, RTX 4000 SFF Ada 20 GB, x86_64, CUDA 13.4,
  Ubuntu 26.04. The x86 validation machine; same GPU generation as HF Jobs' L4. It keeps its own
  golden outputs (GPU numerics differ between machines; compare across machines at CER level).
- No macOS in this phase.
- torch: the PyPI 2.14 wheels are the CUDA 13 build on Linux (aarch64 and x86_64), which the GB10
  needs; 2.14 is kraken's upper bound. torch never changes as a side effect of a resolve
  (a new dependency with its own torch bound, another package index, `uv run --with` on Jobs):
  a change of build is deliberate, applies to one named environment and is recorded in NOTES.md,
  and parity is then compared at CER level, not against the goldens.

## Hugging Face Jobs

Namespace `finebooks` (its free credits; cap agreed per session, report the cost of every run),
flavor `l4x1`, outputs and datatrove `logging_dir` in the private bucket
`hf://buckets/finebooks/linecaster-runs`. Always a small smoke job before a full run.
datatrove's `JobsPipelineExecutor` is experimental and dill-pickles the pipeline, so the launching
machine and the Jobs must run the same Python minor version (3.12). `uv run --with` drops
`[tool.uv.sources]`, so git dependencies (e.g. the kraken fork) must be spelled out, or the job
must run from an image built from the lock.

## Working style

Small commits with plain messages. Record measurements and anything that cannot be validated on
these machines in NOTES.md (to be created) instead of guessing.
