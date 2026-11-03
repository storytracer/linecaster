# linecaster

<p align="center">
  <img src="docs/linecaster.png" alt="Line drawing of an Intertype C4 linecaster, a hot-metal typesetting machine" width="420">
</p>
<p align="center"><sub>An Intertype C4 linecaster (1961). Drawing after a photograph in the Science Museum Group
Collection, CC BY-NC-SA 4.0. <a href="#image-credit">Credit</a></sub></p>

**Composable text recognition for printed and handwritten documents.**

A linecaster was the machine that set metal type one line at a time. This project works in the other
direction: it reads printed lines back into text.

linecaster turns page images into text. You build the recognition chain from small, interchangeable
blocks: a layout model, a line detector, a text recogniser, table and formula models, then
post-processing such as Unicode normalisation, dehyphenation and reflow. The chain is a
[datatrove](https://github.com/huggingface/datatrove) pipeline, so the same code runs on a laptop, a
GPU workstation, a Slurm or Ray cluster, or Hugging Face Jobs.

linecaster is in early development. The concepts below are settled; names and signatures may still
change.

## Principles

- **Every step is replaceable.** Layout, line detection, recognition, tables and formulas are separate
  blocks. Any layout model works with any line detector and any recogniser, as long as each reads and
  writes the shared data model.
- **One data model is the contract.** Every block reads a page's `Transcription` and adds its part:
  regions, lines, words, tables, a document structure. Nothing passes between blocks except this
  record, so blocks stay independent of each other.
- **A page's result depends only on that page.** Pages are processed one at a time; a model batches
  only within a page, in a fixed order. A run gives the same output on one machine or a hundred,
  whatever else is in flight.
- **The text as written is kept.** Recognition produces the text as it appears on the page. Readable
  versions (long s folded, hyphens joined, paragraphs flowed) are derived from it and stored next to
  it, never in its place. Spelling is never modernised.
- **Scaling is the executor's job.** A pipeline does not change when it moves from a laptop to a
  cluster. datatrove splits the work into tasks, resumes failed ones and records what finished.
- **A light core.** The core holds the data model, the blocks and the server. It has no
  machine-learning dependencies. Engines (kraken, PaddleX, vision-language models) are separate
  packages with their own environments.
- **Open formats out.** ALTO, PAGE-XML, hOCR, plain text, Markdown and DoclingDocument, with word
  coordinates where the recogniser provides them.

## Architecture

```
            pipeline (CPU)                                   model servers (GPU)

 reader ─▶ layout ─▶ lines ─▶ recognition ─▶ … ─▶ writer     ┌──────────────────────┐
             │         │           │                         │   linecaster serve   │
             └─────────┴───────────┴──── saturate ──────────▶│  layout, lines,      │
                                                             │  recognition, ...    │
 CPU blocks (reading order, typography, reflow,              └──────────────────────┘
 text variants, checks) run in the pipeline itself           ┌──────────────────────┐
                                                             │  vLLM or any OpenAI- │
                                                             │  compatible server   │
                                                             └──────────────────────┘
```

**Servers host models; the pipeline composes the chain.** A model step is a block with a *backend*,
which says where its model runs:

- `InProcess("package:Class", **kwargs)` loads the model in the pipeline's own process. This is always
  available. It is the reference for checking results and the simple way to run on a CPU.
- `Served(endpoint, model=name)` sends pages to a model server through
  [saturate](https://github.com/davanstrien/saturate). saturate keeps enough pages in flight that the
  server never waits, backs off when the server is busy, and returns results in page order.

`linecaster serve` is the model server for engine models. It loads several models on one GPU, keeps
no state between requests, and speaks the queue metrics saturate reads. Vision-language models run
behind vLLM or any OpenAI-compatible server and are reached the same way.

Different steps work on different pages at the same time: while recognition reads page *n*, layout is
already on a later page. CPU work stays in the pipeline, GPU work stays in the servers.

## The data model

| Class | What it holds |
|---|---|
| `Item` | a multi-page unit: book, issue, manuscript, file |
| `Page` | one page: its image and any number of named transcriptions |
| `Transcription` | regions, lines and words with geometry, reading order and confidences, plus a DoclingDocument |
| `Text` | the text of a whole item in one variant |

Coordinates are pixels of the page image, boxes are `[x, y, width, height]`, and polygons and
baselines are lists of points. A `Transcription` round-trips through JSON exactly and through ALTO,
PAGE-XML and hOCR without losing structure, text, geometry or confidences. See `specs/` for the full
design.

## Text variants

Text is described along three independent axes. Each transform moves one step on one axis.

| Axis | Steps |
|---|---|
| Characters | as written → normalised → expanded → regularised |
| Flow | as laid out → flowed |
| Scope | full page → body only |

Three variants are named:

- `verbatim_txt`: as written, as laid out, full page.
- `readable_txt` and `readable_md`: normalised characters, flowed paragraphs with hyphens joined, body
  text only.

All text is NFC. Normalisation folds typographic forms such as long s, ligatures and r rotunda, and
keeps letters such as æ, œ, ø and ß.

## Install

linecaster needs Python 3.12 and [uv](https://docs.astral.sh/uv/) 0.13.6 or newer.

```bash
git clone https://github.com/storytracer/linecaster && cd linecaster
uv sync                                  # the core
(cd envs/kraken-paddlex && uv sync)      # an environment with the kraken and PaddleX engines
```

Engines conflict in their pinned dependencies, so each combination of engines has its own
environment under `envs/`.

## Using linecaster

### Compose a pipeline

A pipeline is a list of blocks. This one reads a folder of page images, finds regions and lines,
recognises the text and writes one row per page plus ALTO and Markdown files:

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

Swap any model step for another backend or another engine without touching the rest of the chain.

### Serve the models

To move the models onto a GPU server, start `linecaster serve` in the engine environment and change
the backends to `Served`:

```bash
envs/kraken-paddlex/.venv/bin/python -m linecaster.cli serve --port 8100 \
    --model layout=linecaster_paddlex:PaddleLayoutModel --kwargs 'layout={"model_name": "PP-DocLayoutV3"}' \
    --model lines=linecaster_paddlex:PaddleLineModel --kwargs 'lines={"model_name": "PP-OCRv6_medium_det"}' \
    --model recognition=linecaster_kraken:KrakenRecognitionModel --kwargs 'recognition={"model": "medium"}'
```

```python
from linecaster.backends import Served

server = "http://127.0.0.1:8100/v1"
LayoutStep(Served(server, model="layout"))
LinesStep(Served(server, model="lines"))
RecognitionStep(Served(server, model="recognition"))
```

The server also accepts a JSON file with the same models (`--config models.json`). It binds to
loopback by default.

### Use a vision-language model

`ChatPageStep` sends whole pages to an OpenAI-compatible server; `ChatRegionStep` sends one crop per
layout region. A small model spec in `linecaster.models` holds the prompt, sampling, server flags and
how to read the answer:

```python
from linecaster.blocks.chat import ChatPageStep
from linecaster.models import chat_model

spec = chat_model("lightonai/LightOnOCR-2-1B")
ChatPageStep(spec, Served("http://127.0.0.1:8000/v1", model=spec.model))
```

### Scale out

Any datatrove executor runs the same pipeline. For one GPU per task on Hugging Face Jobs, put the
server block last so the server lives until every page is written:

```python
from datatrove.executor import JobsPipelineExecutor
from linecaster.blocks.serve import ServeModels
from linecaster.jobs import dependencies

pipeline = [..., PageJsonlWriter("hf://buckets/<namespace>/<bucket>/run/rows"), ServeModels(models, port=8100)]
JobsPipelineExecutor(pipeline, tasks=16, flavor="l4x1", dependencies=dependencies("<pushed commit>"),
                     logging_dir="hf://buckets/<namespace>/<bucket>/run/logs").run()
```

`ServeChatModel` does the same for vLLM. `GPUJobsExecutor` runs one task per GPU on multi-GPU
flavors. `recipes/hf-jobs/` has complete examples.

### Chain pipelines

Long runs are split into pipelines that each add one part to the page rows. `PageRowReader` reads
the rows an earlier pipeline wrote, fetches the images again and carries everything forward. Pages
that fail a check go to `rejects/` with the reason, and originals are never modified.

## Extending linecaster

- **An engine model** is a class with `step`, `name`, `load()` and
  `__call__(image, transcription, **params) -> Transcription`. Package it under `backends/` and it
  works in-process and behind `linecaster serve`.
- **A vision-language model** is a `ChatModel` subclass: model id, revision, sampling, server flags,
  `request()` and the parsing of its answer. Register it in `linecaster.models`.
- **A CPU step** is a `PageStep`: implement `process_page(doc, page)` and return the page.

Connectors in linecaster stay generic: folders, buckets and Hugging Face datasets. Adapters for a
particular collection or institution belong in the projects that use linecaster.

## Repository layout

```
src/linecaster/        data model, blocks, model server, model specs, Jobs helpers
backends/              engine packages (linecaster-kraken, linecaster-paddlex)
envs/                  environments that install engines together
examples/, recipes/    complete pipelines, local and on Hugging Face Jobs
specs/                 design of the data model and the serialisers
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
