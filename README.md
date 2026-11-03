# Linecaster

### Composable text recognition for printed and handwritten documents

<p align="center">
  <img src="docs/linecaster.png" alt="Line drawing of an Intertype C4 linecaster, a hot-metal typesetting machine" width="353">
</p>
<p align="center"><sub>An Intertype C4 linecaster (1961). Drawing after a photograph in the Science Museum Group
Collection, CC BY-NC-SA 4.0. <a href="#image-credit">Credit</a></sub></p>

linecaster turns scanned pages into text you can read, search and train on. It works on printed books
and on handwriting, old and new.

You build the recognition chain from small steps: find the regions on a page, find the lines, read
them, rebuild the tables, clean up the text. Each step is a separate building block, so you can swap
one model for another without touching the rest. The same chain runs on a laptop, on a GPU
workstation or on hundreds of machines.

linecaster is in early development. The ideas below are settled; names and signatures may still change.

## What you get

For every page:

- **The text as written**, line by line, exactly as the page shows it.
- **Readable text**, with old letterforms such as long s folded, line-end hyphens joined and
  paragraphs flowed across lines and pages.
- **Markdown** with headings, tables and formulas.
- **ALTO, PAGE-XML and hOCR**, the formats libraries and viewers use, with the position of every word.
- **A page row** that keeps every intermediate result, so later work can start where earlier work
  stopped.

For every book or other multi-page item, the same text joined into one file per variant.

## How it works

### A chain of steps

A page goes through a fixed series of steps. Some steps run a model: a layout model finds text blocks,
headings and tables; a line detector finds the lines; a recogniser reads each line. Other steps are
plain processing: assigning lines to their blocks, normalising Unicode, removing typographic debris and
assembling the document.

Each step is a block in a [datatrove](https://github.com/huggingface/datatrove) pipeline. A pipeline is
simply a list of blocks, and any layout model can be combined with any line detector and any recogniser.

### Every step adds to one record

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture-dark.svg">
  <img src="docs/architecture-light.svg" width="760" alt="One page through a linecaster pipeline: page images are read, then layout, line detection, line assignment, recognition, tables, Unicode and typography and document assembly each add a part to the page's Transcription. The four model steps send the page through saturate to linecaster serve on a GPU and get it back with their part added. Pages with errors go to rejects; the rest are written as page rows, ALTO, PAGE, hOCR, text and Markdown. The executor runs many copies of this task.">
</picture>

*The path of one page. Shaded steps run a model. On the left, what the page's record holds after each
step.*

The steps share one record per page, its `Transcription`. The layout step adds regions, the line step
adds lines, the recogniser adds text and words, and so on. Steps never talk to each other directly; they
only read and extend this record. That is what makes them interchangeable.

A page that fails along the way is not lost. It carries its error past the remaining model steps and
is written with it; a check step (`ValidatePages`, `RejectSink`) sends such pages to `rejects/` together
with the reason.

### Models run where they fit

Every model step has a *backend* that says where its model runs:

- **In-process.** The model loads inside the pipeline. This is the simplest setup, works on a CPU, and
  is the reference when you check results.
- **Served.** The model runs on a GPU server and the step sends pages to it. `linecaster serve` keeps
  several engine models loaded on one GPU. Vision-language models run behind vLLM or any other
  OpenAI-compatible server.

Served steps talk to their servers through [saturate](https://github.com/davanstrien/saturate). saturate
keeps enough pages in flight that the server never waits, slows down when the server is busy, and
passes each page on as soon as it is done. Because each model step has its own connection, the steps overlap: while
the recogniser reads one page, the layout model is already on a later one.

### From one machine to many

A pipeline does not change when it grows. datatrove's executors split the pages into tasks and run them
on a single machine, a Slurm or Ray cluster, or Hugging Face Jobs. They record which tasks finished, so
an interrupted run resumes where it stopped.

A page's result depends only on that page. Models batch lines within a page in a fixed order and never
mix pages, so a run gives the same output on one machine or on a hundred.

## Getting started

### Install

linecaster needs Python 3.12 and [uv](https://docs.astral.sh/uv/) 0.13.6 or newer.

```bash
git clone https://github.com/storytracer/linecaster && cd linecaster
uv sync                                  # the core
(cd envs/kraken-paddlex && uv sync)      # an environment with the kraken and PaddleX engines
```

The core has no machine-learning dependencies. The engines bring their own, which often conflict, so
each combination of engines gets its own environment under `envs/`.

### Your first pipeline

This pipeline reads a folder of scans, finds regions and lines, reads the text and writes ALTO and
Markdown files plus one row per page. Run it with the engine environment's Python.

```python
from datatrove.executor import LocalPipelineExecutor

from linecaster.backends import InProcess
from linecaster.blocks.document import AssembleDocument, Typography
from linecaster.blocks.lines import AssignLinesToRegions
from linecaster.blocks.models import LayoutStep, LinesStep, RecognitionStep
from linecaster.blocks.readers import ImageFolderReader
from linecaster.blocks.unicode import NormalizeUnicode
from linecaster.blocks.writers import PageFilesWriter, PageJsonlWriter

pipeline = [
    ImageFolderReader("scans/", item_from_parent=True),      # one subfolder per book
    LayoutStep(InProcess("linecaster_paddlex:PaddleLayoutModel", model_name="PP-DocLayoutV3")),
    LinesStep(InProcess("linecaster_paddlex:PaddleLineModel", model_name="PP-OCRv6_medium_det")),
    AssignLinesToRegions(),
    RecognitionStep(InProcess("linecaster_kraken:KrakenRecognitionModel", model="medium")),
    NormalizeUnicode(),
    Typography(),
    AssembleDocument(),
    PageFilesWriter("out/files", formats=("alto", "md")),
    PageJsonlWriter("out/rows"),
]

LocalPipelineExecutor(pipeline, tasks=4, logging_dir="out/logs").run()
```

### Move the models to a GPU server

Start `linecaster serve` in the engine environment:

```bash
envs/kraken-paddlex/.venv/bin/python -m linecaster.cli serve --port 8100 \
    --model layout=linecaster_paddlex:PaddleLayoutModel --kwargs 'layout={"model_name": "PP-DocLayoutV3"}' \
    --model lines=linecaster_paddlex:PaddleLineModel --kwargs 'lines={"model_name": "PP-OCRv6_medium_det"}' \
    --model recognition=linecaster_kraken:KrakenRecognitionModel --kwargs 'recognition={"model": "medium"}'
```

Then change only the backends. Everything else in the pipeline stays the same:

```python
from linecaster.backends import Served

server = "http://127.0.0.1:8100/v1"
LayoutStep(Served(server, model="layout"))
LinesStep(Served(server, model="lines"))
RecognitionStep(Served(server, model="recognition"))
```

The server can also read its models from a JSON file (`--config models.json`). It listens on loopback
only, unless you tell it otherwise.

### Read pages with a vision-language model

`ChatPageStep` sends whole pages to an OpenAI-compatible server. `ChatRegionStep` sends one crop per
layout region instead. A short model spec in `linecaster.models` holds the model's prompt, sampling,
server flags and how to read its answer:

```python
from linecaster.blocks.chat import ChatPageStep
from linecaster.models import chat_model

spec = chat_model("lightonai/LightOnOCR-2-1B")
ChatPageStep(spec, Served("http://127.0.0.1:8000/v1", model=spec.model))
```

### Run on Hugging Face Jobs

With one GPU per Job, each Job starts its own model server. Put the server block last in the pipeline,
so the server stays up until every page is written:

```python
from datatrove.executor import JobsPipelineExecutor
from linecaster.blocks.serve import ServeModels
from linecaster.jobs import dependencies

pipeline = [..., PageJsonlWriter("hf://buckets/<namespace>/<bucket>/run/rows"), ServeModels(models, port=8100)]
JobsPipelineExecutor(pipeline, tasks=16, flavor="l4x1", dependencies=dependencies("<pushed commit>"),
                     logging_dir="hf://buckets/<namespace>/<bucket>/run/logs").run()
```

`ServeChatModel` does the same for vLLM. On machines with several GPUs, `GPUJobsExecutor` runs one task
per GPU. `recipes/hf-jobs/` has complete examples.

### Split long runs into stages

A large job is easier to run, check and repeat in stages. Each stage reads the page rows the previous
one wrote (`PageRowReader`), adds one part and writes complete rows again. The original files are never
changed; rejected pages and their reasons go to `rejects/`, and datatrove's logs and completion markers
go to `logs/`.

## Under the hood

### The data model

| Class | What it holds |
|---|---|
| `Item` | a multi-page unit: book, issue, manuscript, file |
| `Page` | one page: its image and any number of named transcriptions |
| `Transcription` | regions, lines and words with positions, reading order and confidences, plus a DoclingDocument |
| `Text` | the text of a whole item in one variant |

A page can hold several transcriptions side by side, for example a delivered OCR text, a new
recognition and the ground truth.

Positions are pixels of the page image. Boxes are `[x, y, width, height]`; polygons and baselines are
lists of points. A `Transcription` survives a round trip through JSON exactly, and through ALTO,
PAGE-XML and hOCR without losing structure, text, positions or confidences. `specs/` describes the
design in full.

### Text variants

linecaster describes text along three independent axes. Each transform moves one step on one axis and
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

## Design principles

- **Every step is replaceable.** Steps share a data model and nothing else.
- **The text as written is kept.** Readable versions are derived from it and stored next to it.
- **Results are reproducible.** A page's output depends only on the page and the pinned models.
- **Scaling belongs to the executor.** The pipeline stays the same from one machine to many.
- **The core stays light.** Engines are separate packages with their own environments.
- **Connectors stay generic.** Folders, buckets and Hugging Face datasets are built in. Adapters for a
  particular collection or institution belong in the projects that use linecaster.
- **Open formats out.** ALTO, PAGE-XML, hOCR, plain text, Markdown and DoclingDocument.

## Extending linecaster

- **A new engine model** is a class with `step`, `name`, `load()` and
  `__call__(image, transcription, **params) -> Transcription`. Package it under `backends/` and it runs
  in-process and behind `linecaster serve`.
- **A new vision-language model** is a `ChatModel` subclass with the model id, revision, sampling,
  server flags, `request()` and the parsing of its answer. Register it in `linecaster.models`.
- **A new processing step** is a `PageStep`: implement `process_page(doc, page)` and return the page.

## Repository layout

```
src/linecaster/        data model, blocks, model server, model specs, Jobs helpers
backends/              engine packages (linecaster-kraken, linecaster-paddlex)
envs/                  environments that install engines together
examples/, recipes/    complete pipelines, local and on Hugging Face Jobs
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
