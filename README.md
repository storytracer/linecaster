# Linecaster

### Modular OCR pipelines you can run anywhere

<p align="center">
  <img src="docs/linecaster.png" alt="Line drawing of an Intertype C4 linecaster, a hot-metal typesetting machine" width="353">
</p>
<p align="center"><sub>An Intertype C4 linecaster (1961). Drawing after a photograph in the Science Museum Group
Collection, CC BY-NC-SA 4.0. <a href="#image-credit">Credit</a></sub></p>

Linecaster lets you build an OCR pipeline from interchangeable parts, and run that same pipeline on any
machine: a laptop, a GPU server, a cluster, or Hugging Face Jobs. Moving from a test on ten pages to a run
on millions does not mean rewriting anything. Neither does swapping one OCR model for a newer one.

Linecaster is in early development. The ideas below are settled; names and options may still change.

## Why Linecaster

Reading a scanned page takes several models: one finds the layout, one finds the lines, one reads them,
others rebuild tables or formulas. Each of these models comes from a different project, with its own
software, its own way of running and its own output. And every place you might run them, from your own
GPU to a rented cluster or Hugging Face Jobs, has its own way of starting work, spreading it over
machines and coping with failures.

So in practice the choice of models and the choice of machines get tangled up. A new recogniser means
reworking the whole setup. A larger collection means writing new scripts for the cluster. A team that
wants to compare a classic OCR engine with one of the new vision-language models has to build two
separate pipelines.

Linecaster pulls these apart:

- **Any OCR component.** Layout, line detection, recognition, tables and formulas are separate steps.
  Each step can use a model from a different engine: kraken, PaddleX, or a vision-language model served
  by vLLM. Every step reads and writes the same record per page, so they combine freely.
- **Any machine.** You define the pipeline once. The same definition runs on one laptop, on one GPU, on
  every GPU of a server, on a Ray cluster, or on Hugging Face Jobs. Only the line that starts the run
  changes.
- **Models served where they are needed.** A model can run inside the pipeline, or on a GPU server that
  the pipeline talks to. On a cluster, each task starts its own model server on its GPU, so there is no
  separate serving system to set up.
- **The same result everywhere.** The text for a page depends only on that page and the models, never on
  how many machines share the work or what else was running at the time.
- **Built for long runs.** Work is split into tasks. A crashed run resumes where it stopped, and damaged
  pages are set aside with the reason instead of stopping everything.

## What you get

For every page:

- **The text exactly as printed**, line by line, with its original spellings, letterforms and line
  breaks. This is the version to check against a hand-made transcription.
- **A readable version**, where old letterforms such as the long s (ſ) become their modern forms, words
  split by a hyphen at the end of a line are joined again, and lines are joined into paragraphs.
- **Markdown** with headings, tables and formulas, and the same document as HTML, DocLang or
  DoclingDocument JSON.
- **Library formats** (ALTO, PAGE-XML, hOCR) that record where each word sits on the page, so viewers
  can highlight search hits on the scan.
- **One record per page** that keeps every intermediate result, so later work can start where earlier
  work stopped.

For every book, the same text is also joined into one file per version.

## Design principles

- **Every step is replaceable.** Steps share a data model and nothing else.
- **Deployment is not part of the pipeline.** Executors and backends change; the steps do not.
- **The text as written is kept.** Readable versions are derived from it and stored next to it.
- **The core stays light.** Engines are separate packages with their own environments.
- **Connectors stay generic.** Folders, buckets and Hugging Face datasets are built in. Adapters for a
  particular collection or institution belong in the projects that use Linecaster.
- **Open formats out.** ALTO, PAGE-XML, hOCR, plain text, Markdown, HTML, DocLang and DoclingDocument.

## Under the hood

### The data model

| Class | What it holds |
|---|---|
| `Item` | a multi-page unit: book, issue, manuscript, file |
| `Page` | one page: its image and any number of named transcriptions |
| `Transcription` | regions, lines and words with positions, reading order and confidences, plus a DoclingDocument |
| `Text` | the text of a whole item in one version |

A page can hold several transcriptions side by side, for example a delivered OCR text, a new
recognition and the ground truth.

Positions are pixels of the page image. Boxes are `[x, y, width, height]`; polygons and baselines are
lists of points. A `Transcription` survives a round trip through JSON exactly, and through ALTO,
PAGE-XML and hOCR without losing structure, text, positions or confidences. `specs/` describes the
design in full.

### Text versions

Linecaster describes text along three independent axes. Each transform moves one step on one axis and
leaves the others alone.

| Axis | From | To |
|---|---|---|
| Characters | as written | normalised, expanded, regularised |
| Flow | as laid out | flowed |
| Scope | full page | body text only |

Three combinations have names:

- `verbatim_txt`: as written, as laid out, the full page.
- `readable_txt` and `readable_md`: normalised characters, flowed paragraphs with hyphens joined, body
  text only.

All text is in Unicode NFC. Normalisation folds typographic forms such as long s, ligatures and
r rotunda, and keeps letters such as æ, œ, ø and ß. Spelling is never modernised.

### Why results are the same everywhere

Models batch only the lines of one page, in a fixed order, and never mix pages. Model versions are
pinned, and numerically relevant library versions are fixed per engine environment. A page's output
therefore depends on the page and the models, not on the machine, the number of GPUs or what else is in
flight. Different GPU types can still differ in the last digits of their arithmetic, which shows up as
rare one-character differences.

## How it works

### A page goes through a chain of steps

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture-dark.svg">
  <img src="docs/architecture-light.svg" width="760" alt="One page through a linecaster pipeline: page images are read, then layout, line detection, line assignment, recognition, tables, Unicode and typography and document assembly each add a part to the page's Transcription. The four model steps send the page through saturate to linecaster serve on a GPU and get it back with their part added. Pages with errors go to rejects; the rest are written as page rows, ALTO, PAGE, hOCR, text and Markdown. The executor runs many copies of this task.">
</picture>

*The path of one page. Shaded steps run a model. On the left, what the page's record holds after each
step.*

A page is read in stages, much as a person would read it: first see where the text blocks, headings and
tables are, then find each line, read the lines, rebuild the tables, tidy up the characters, and finally
put everything together in reading order.

Each page travels with one record, its `Transcription`, a bit like a form that every step fills in
further. The layout step adds the text blocks, the line step adds the lines, the recogniser adds the text
and the position of each word. Steps never talk to each other directly; they only read and extend this
record. That is why any step can be replaced.

### Each model step chooses where its model runs

A model step has a *backend*:

- **In-process:** the model loads inside the pipeline. Simplest, works without a GPU, and the reference
  when checking results.
- **Served:** the model stays loaded on a GPU server and the step sends pages to it. `linecaster serve`
  hosts the engine models (kraken, PaddleX); vision-language models run behind vLLM or any other
  OpenAI-compatible server.

Served steps reach their servers through [saturate](https://github.com/davanstrien/saturate), which keeps
enough pages in flight that the GPU never waits. Different steps work on different pages at the same
time: while one page is being read, the layout of the next one is already being found.

### The executor decides where the pipeline runs

Pipelines are [datatrove](https://github.com/huggingface/datatrove) pipelines, Hugging Face's library for
large data-processing jobs. datatrove splits the pages into tasks and hands them to an *executor*: on one
machine, on a Ray cluster, or on Hugging Face Jobs. It records which tasks have finished, so an
interrupted run picks up where it stopped. datatrove also has a Slurm executor; Linecaster has not been
run on Slurm yet.

When a task brings its own GPU, the last block of the pipeline starts the model server for that task and
stops it when the task's pages are written. On a machine with several GPUs, each task gets one GPU and a
server of its own.

## Getting started

### Install

Linecaster needs Python 3.12 and [uv](https://docs.astral.sh/uv/) 0.13.6 or newer.

```bash
git clone https://github.com/storytracer/linecaster && cd linecaster
uv sync                                  # the core
(cd envs/kraken-paddlex && uv sync)      # an environment with the kraken and PaddleX engines
```

The core has no machine-learning dependencies. Engines bring their own, which often conflict, so each
combination of engines gets its own environment under `envs/`.

### Define the pipeline once

```python
from linecaster.backends import InProcess, Served
from linecaster.blocks.document import AssembleDocument, Typography
from linecaster.blocks.lines import AssignLinesToRegions
from linecaster.blocks.models import LayoutStep, LinesStep, RecognitionStep, TablesStep
from linecaster.blocks.readers import ImageFolderReader
from linecaster.blocks.unicode import NormalizeUnicode
from linecaster.blocks.writers import PageFilesWriter, PageJsonlWriter

MODELS = [
    {"name": "layout", "spec": "linecaster_paddlex:PaddleLayoutModel", "kwargs": {"model_name": "PP-DocLayoutV3"}},
    {"name": "lines", "spec": "linecaster_paddlex:PaddleLineModel", "kwargs": {"model_name": "PP-OCRv6_medium_det"}},
    {"name": "recognition", "spec": "linecaster_kraken:KrakenRecognitionModel", "kwargs": {"model": "medium"}},
    {"name": "tables", "spec": "linecaster_paddlex:PaddleTableModel", "kwargs": {}},
]

def in_process(name):                        # the model loads inside the pipeline
    m = next(m for m in MODELS if m["name"] == name)
    return InProcess(m["spec"], **m["kwargs"])

def served(name):                            # the model runs on a server
    return Served("http://127.0.0.1:8100/v1", model=name)

def ocr(images, out, backend):
    return [
        ImageFolderReader(images, item_from_parent=True),      # one subfolder per book
        LayoutStep(backend("layout")),
        LinesStep(backend("lines")),
        AssignLinesToRegions(),
        RecognitionStep(backend("recognition")),
        NormalizeUnicode(),
        TablesStep(backend("tables")),
        Typography(),
        AssembleDocument(),
        PageFilesWriter(f"{out}/files", formats=("alto", "md")),
        PageJsonlWriter(f"{out}/rows"),
    ]
```

### Run it anywhere

**On a laptop or any single machine**, models in-process:

```python
from datatrove.executor import LocalPipelineExecutor

LocalPipelineExecutor(ocr("scans/", "out", in_process), tasks=4, logging_dir="out/logs").run()
```

**On a GPU server.** Start `linecaster serve` in the engine environment, then use the served backend:

```bash
envs/kraken-paddlex/.venv/bin/python -m linecaster.cli serve --port 8100 \
    --model layout=linecaster_paddlex:PaddleLayoutModel --kwargs 'layout={"model_name": "PP-DocLayoutV3"}' \
    --model lines=linecaster_paddlex:PaddleLineModel --kwargs 'lines={"model_name": "PP-OCRv6_medium_det"}' \
    --model recognition=linecaster_kraken:KrakenRecognitionModel --kwargs 'recognition={"model": "medium"}' \
    --model tables=linecaster_paddlex:PaddleTableModel
```

```python
LocalPipelineExecutor(ocr("scans/", "out", served), tasks=4, logging_dir="out/logs").run()
```

**On every GPU of one or many machines, with Ray.** Each task gets a GPU and starts its own server:

```python
from linecaster.blocks.serve import ServeModels
from linecaster.ray_executor import RayGPUExecutor

pipeline = ocr("/shared/scans", "/shared/out", served) + [
    ServeModels(MODELS, port=8100, python="envs/kraken-paddlex/.venv/bin/python")]   # last block
RayGPUExecutor(pipeline, tasks=64, logging_dir="/shared/out/logs").run()
```

Start Ray first (`uv sync --extra ray`, then `ray start` on each machine). Images and output must be on
storage every machine can reach.

**On Hugging Face Jobs**, one GPU per Job:

```python
from datatrove.executor import JobsPipelineExecutor
from linecaster.jobs import dependencies

run = "hf://buckets/<namespace>/<bucket>/my-run"
pipeline = ocr("hf://datasets/<namespace>/<dataset>/images", run, served) + [ServeModels(MODELS, port=8100)]
JobsPipelineExecutor(pipeline, tasks=64, flavor="l4x1", namespace="<namespace>",
                     dependencies=dependencies("<pushed linecaster commit>"), logging_dir=f"{run}/logs").run()
```

On flavors with several GPUs (`l4x4`, `l40sx8`), `linecaster.jobs.GPUJobsExecutor` runs one task per GPU.
`recipes/` has complete versions of these pipelines.

### Use a vision-language model

`ChatPageStep` sends whole pages to an OpenAI-compatible server; `ChatRegionStep` sends one crop per
layout region. A short model spec in `linecaster.models` holds the model's prompt, sampling, server flags
and how to read its answer. They fit into the same pipelines and executors:

```python
from linecaster.blocks.chat import ChatPageStep
from linecaster.models import chat_model

spec = chat_model("lightonai/LightOnOCR-2-1B")
ChatPageStep(spec, Served("http://127.0.0.1:8000/v1", model=spec.model))
```

`ServeChatModel` starts vLLM (or SGLang, for a spec that needs it) inside a task, the way `ServeModels`
starts `linecaster serve`.

### Split long runs into stages

A large job is easier to run, check and repeat in stages. Each stage reads the page rows the previous
one wrote (`PageRowReader`), adds one part and writes complete rows again. The original files are never
changed. A check step (`ValidatePages`, `RejectSink`) puts pages that failed into `rejects/` with the
reason, and datatrove keeps its logs and completion markers in `logs/`.

## Extending Linecaster

- **A new engine model** is a class with `step`, `name`, `load()` and
  `__call__(image, transcription, **params) -> Transcription`. Package it under `backends/` and it runs
  in-process and behind `linecaster serve`.
- **A new vision-language model** is a `ChatModel` subclass with the model id, revision, sampling,
  server flags, `request()` and the parsing of its answer. Register it in `linecaster.models`.
- **A new processing step** is a `PageStep`: implement `process_page(doc, page)` and return the page.

## Repository layout

```
src/linecaster/        data model, blocks, model server, model specs, executors and Jobs helpers
backends/              engine packages (linecaster-kraken, linecaster-paddlex)
envs/                  environments that install engines together
examples/, recipes/    complete pipelines: local, Ray, Hugging Face Jobs
specs/                 design of the data model and the serialisers
docs/                  images for this README
```

## Licence

The code is licensed under Apache-2.0, see [LICENSE](LICENSE). The drawing in `docs/linecaster.png`
has its own licence, below.

### Image credit

The drawing of the linecaster is by Sebastian Majstorovic, made with Adobe Illustrator and Google
Gemini. It is based on a photograph of the
[Intertype C4 Linecaster](https://collection.sciencemuseumgroup.org.uk/objects/co8407592/intertype-c4-linecaster)
(Intertype Ltd, Slough, 1961; object Y1990.104.12, gift of M.H. Whittaker & Son) in the Science
Museum Group Collection. Photograph © The Board of Trustees of the Science Museum, released under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). The photograph was redrawn as a
black-and-white line drawing.

The drawing is an adaptation of that photograph and is licensed under the same terms,
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). It may not be used for
commercial purposes. The Apache-2.0 licence of the code does not apply to it.
