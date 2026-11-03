# Linecaster

### Modular OCR pipelines you can run anywhere

<p align="center">
  <img src="docs/linecaster.png" alt="Line drawing of an Intertype C4 linecaster, a hot-metal typesetting machine" width="353">
</p>
<p align="center"><sub>An Intertype C4 linecaster (1961). Drawing after a photograph in the Science
Museum Group Collection, CC BY-NC-SA 4.0. <a href="#-licence">Credit</a></sub></p>

Build an OCR pipeline from interchangeable parts. Run the same pipeline on a laptop, a GPU server, a
cluster or [Hugging Face Jobs][HF Jobs].

> [!NOTE]
> Linecaster is in early development. The ideas are settled; names and options may still change.

**Jump to:** [Why](#-why-linecaster) · [Quick start](#-quick-start) · [How it works](#-how-it-works) ·
[Run anywhere](#-run-it-anywhere) · [Outputs](#-what-you-get) · [Models](#-supported-models) ·
[Reference](#-reference)

## 🤔 Why Linecaster

Reading a scanned page takes several models: one for the layout, one for the lines, one to read them,
others for tables and formulas. Each comes with its own software. Each machine you might run them on
has its own way of starting and scaling work. Swapping a model or moving to bigger hardware usually
means starting over.

Linecaster keeps the two apart:

- 🧩 **Any component.** Layout, lines, recognition, tables and formulas are separate steps. Mix models
  from [kraken] and [PaddleX] with [twenty vision-language models](#-vision-language-models).
- 🌍 **Any machine.** Define the pipeline once. Only the line that starts the run changes.
- 🖥️ **No serving stack to build.** Models load inside the pipeline, or each task starts its own model
  server on its GPU.
- 🎯 **The same result everywhere.** A page's text depends only on that page, never on how many
  machines share the work.
- 🔁 **Built for long runs.** Interrupted runs resume. Damaged pages are set aside with the reason.

## 🚀 Quick start

You need Python 3.12 and [uv](https://docs.astral.sh/uv/) 0.13.6 or newer.

```bash
git clone https://github.com/storytracer/linecaster
cd linecaster
uv sync
# the kraken + PaddleX engines:
(cd envs/kraken-paddlex && uv sync)
```

A pipeline is a list of blocks. Save this as `ocr.py`. It reads a folder of scans and writes Markdown
and ALTO:

```python
from datatrove.executor import LocalPipelineExecutor
from linecaster.backends import InProcess as P
from linecaster.blocks.document import AssembleDocument
from linecaster.blocks.lines import AssignLinesToRegions
from linecaster.blocks.models import (
    LayoutStep, LinesStep, RecognitionStep)
from linecaster.blocks.readers import ImageFolderReader
from linecaster.blocks.writers import PageFilesWriter

pipeline = [
    ImageFolderReader("scans/"),
    LayoutStep(P("linecaster_paddlex:PaddleLayoutModel")),
    LinesStep(P("linecaster_paddlex:PaddleLineModel")),
    AssignLinesToRegions(),
    RecognitionStep(
        P("linecaster_kraken:KrakenRecognitionModel")),
    AssembleDocument(),
    PageFilesWriter("out/", formats=("md", "alto")),
]
LocalPipelineExecutor(
    pipeline, logging_dir="out/logs").run()
```

Run it with the engine environment's Python. The models download on first use.

```bash
PY=envs/kraken-paddlex/.venv/bin/python
$PY ocr.py
```

`examples/` has fuller pipelines.

## 🧩 How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture-dark.svg">
  <img src="docs/architecture-light.svg" width="760" alt="One page through a linecaster pipeline: page images are read, then layout, line detection, line assignment, recognition, tables, Unicode and typography and document assembly each add a part to the page's Transcription. The four model steps send the page through saturate to linecaster serve on a GPU and get it back with their part added. Pages with errors go to rejects; the rest are written as page rows, ALTO, PAGE, hOCR, text and Markdown. The executor runs many copies of this task.">
</picture>

*The path of one page. Shaded steps run a model.*

Three ideas carry the design:

1. 📋 **One record per page.** Every step reads the page's `Transcription` and adds its part: regions,
   lines, text, tables, a document. Steps never talk to each other, so any step can be replaced.
2. 🔌 **Each model step has a backend.** `InProcess` loads the model inside the pipeline. `Served` sends
   pages to a model server through [saturate], which keeps
   enough pages in flight that the GPU never waits.
3. 🏗️ **The executor decides where it runs.** Pipelines are
   [datatrove] pipelines. Executors split the pages into
   tasks, run them locally, on a [Ray] cluster or on [Hugging Face Jobs][HF Jobs], and resume where a run stopped.

## 🌍 Run it anywhere

The steps stay the same. Only the backends and the executor change.

| Where | Backend and executor |
|---|---|
| 💻 Laptop | `InProcess`<br>`LocalPipelineExecutor` |
| 🖥️ GPU server | `Served`<br>`LocalPipelineExecutor` |
| 🧮 Ray cluster | `Served` + `ServeModels`<br>`RayGPUExecutor` |
| ☁️ HF Jobs | `Served` + `ServeModels`<br>`JobsPipelineExecutor` |

A model server hosts models by name. `examples/squiddle_models.json` is a complete list; in Python:

```python
MODELS = [
    {"name": "layout",
     "spec": "linecaster_paddlex:PaddleLayoutModel"},
    {"name": "lines",
     "spec": "linecaster_paddlex:PaddleLineModel"},
    {"name": "recognition",
     "spec": "linecaster_kraken:KrakenRecognitionModel",
     "kwargs": {"model": "medium"}},
]
```

<details>
<summary><b>🖥️ On a GPU server</b></summary>

Start `linecaster serve` with the models:

```bash
PY=envs/kraken-paddlex/.venv/bin/python
$PY -m linecaster.cli serve --port 8100 \
  --config examples/squiddle_models.json
```

Then give each model step a `Served` backend:

```python
from linecaster.backends import Served

S = "http://127.0.0.1:8100/v1"
LayoutStep(Served(S, "layout"))
LinesStep(Served(S, "lines"))
RecognitionStep(Served(S, "recognition"))
```

The server keeps the models loaded and listens on loopback only.

</details>

<details>
<summary><b>🧮 On every GPU, with Ray</b></summary>

Each task gets one GPU and starts its own server on it. `ServeModels` goes last, so the server lives
until every page is written.

```bash
uv sync --extra ray
.venv/bin/ray start --head --num-gpus 8
# on each other machine:
# ray start --address=<head>:6379
```

```python
from linecaster.blocks.serve import ServeModels
from linecaster.ray_executor import RayGPUExecutor

PY = "envs/kraken-paddlex/.venv/bin/python"
pipeline += [ServeModels(MODELS, python=PY)]
RayGPUExecutor(pipeline, tasks=64,
    logging_dir="/shared/out/logs").run()
```

Images and output must be on storage every machine can reach. A complete version is
`recipes/ray/squiddle_chain.py`.

</details>

<details>
<summary><b>☁️ On Hugging Face Jobs</b></summary>

One Job per task, one GPU per Job. Each Job installs Linecaster at a pushed commit.

```python
from datatrove.executor import JobsPipelineExecutor
from linecaster.jobs import dependencies

pipeline += [ServeModels(MODELS)]
JobsPipelineExecutor(
    pipeline, tasks=64, flavor="l4x1",
    namespace="<namespace>",
    dependencies=dependencies("<commit>"),
    logging_dir="hf://buckets/<ns>/<b>/logs",
).run()
```

On multi-GPU flavors such as `l4x4`, `GPUJobsExecutor` runs one task per GPU. Complete versions are in
`recipes/hf-jobs/`.

</details>

<details>
<summary><b>🤖 With a vision-language model</b></summary>

`ChatPageStep` sends whole pages to an OpenAI-compatible server; `ChatRegionStep` sends one crop per
layout region. A model spec holds the prompt, sampling, server flags and how to read the answer.

```python
from linecaster.blocks.chat import ChatPageStep
from linecaster.models import chat_model

spec = chat_model("rednote-hilab/dots.ocr")
S = "http://127.0.0.1:8000/v1"
ChatPageStep(spec, Served(S, spec.model))
```

`ServeChatModel` starts [vLLM] or [SGLang] inside a task, the way `ServeModels` starts `linecaster serve`.
`recipes/hf-jobs/chat_page.py` runs any spec on Hugging Face Jobs.

</details>

## 📦 What you get

| Output | What it is for |
|---|---|
| 📜 Text as printed | checking against a hand-made transcription |
| 📖 Readable text | reading and training: old letterforms folded, hyphens joined, paragraphs flowed |
| 📝 Markdown, HTML, DocLang, [Docling] JSON | documents with headings, tables and formulas |
| 🏛️ [ALTO], [PAGE-XML], [hOCR] | libraries and viewers: every word with its position |
| 🗂️ Page rows ([JSON Lines], [Parquet]) | later pipelines: every intermediate result |

Files come per page or, for a book, one per version.

## 🤖 Supported models

Every model belongs to one step. Engine models run inside the pipeline or behind `linecaster serve`.
[kraken] models come with the `linecaster-kraken` package, [PaddleX] models with `linecaster-paddlex`.
Vision-language models run behind [vLLM] or [SGLang].

### 🗺️ Layout

`LayoutStep` finds the regions of a page (text blocks, headings, tables, pictures, page numbers) and
their reading order.

| Model | What it gives |
|---|---|
| [PP-DocLayoutV3] | regions as polygons, learned reading order (default) |
| [PP-DocLayout_plus-L] | regions as boxes, reading order from their positions |
| none: `SingleRegionLayout` | the whole page as one text region |

### 📏 Lines

`LinesStep` finds the text lines and assigns each to its region.

| Model | Default |
|---|---|
| [PP-OCRv6 tiny][PP-OCRv6_tiny_det] | |
| [PP-OCRv6 small][PP-OCRv6_small_det] | |
| [PP-OCRv6 medium][PP-OCRv6_medium_det] | ✅ |

### 👁️ Recognition

`RecognitionStep` reads each line and places every word on the page.

| Model | Default |
|---|---|
| [kraken PP-OCRv6 tiny][kraken-tiny] | |
| [kraken PP-OCRv6 small][kraken-small] | |
| [kraken PP-OCRv6 medium][kraken-medium] | ✅ |
| any kraken model file | |

### 📊 Tables

`TablesStep` finds the rows and columns of each table region and fills the cells with the recognised
lines.

| Model | What it does |
|---|---|
| [SLANet_plus] | rows, columns and cell boxes (default) |
| [PP-LCNet table classifier][PP-LCNet_x1_0_table_cls] | tells ruled from unruled tables |
| [RT-DETR-L wired cells][RT-DETR-L_wired_table_cell_det] | cell boxes in ruled tables (`e2e=False`) |
| [RT-DETR-L wireless cells][RT-DETR-L_wireless_table_cell_det] | cell boxes in unruled tables (`e2e=False`) |

### ➗ Formulas

`FormulasStep` reads each formula region as LaTeX.

| Model | Default |
|---|---|
| [PP-FormulaNet_plus-L] | ✅ |
| [PP-FormulaNet-L] | |

### 🤖 Vision-language models

`ChatPageStep` sends the whole page; `ChatRegionStep` sends one crop per layout region. Each spec pins
the model revision. Its settings come from the drivers of the open [bhl-ocr-eval] benchmark, which
follow the models' own instructions.

<details>
<summary><b>Page models</b>: nineteen specs</summary>

| Model | Server |
|---|---|
| [chandra-ocr-2] | vLLM |
| [DeepSeek-OCR] | vLLM |
| [DeepSeek-OCR-2] | vLLM |
| [dots.mocr] | vLLM |
| [dots.ocr] | vLLM |
| [GLM-OCR] | vLLM |
| [LightOnOCR-2-1B] | vLLM |
| [LightOnOCR-3-0.8B] | vLLM |
| [LightOnOCR-3-4B] | vLLM |
| [Nemotron-3.5-Parse] | vLLM |
| [olmOCR-2-7B-1025-FP8] | vLLM |
| [OvisOCR2] | vLLM |
| [OvisOCR3] | vLLM |
| [PaddleOCR-VL-1.6] | vLLM |
| [Qianfan-OCR] | vLLM |
| [Qwen3.5-9B] | vLLM |
| [SmolDocling-256M-preview] | vLLM |
| [Unlimited-OCR] | vLLM |
| [Unlimited-OCR-2] | SGLang |

</details>

<details>
<summary><b>Region models</b>: two specs</summary>

| Model | Server |
|---|---|
| [LightOnOCR-2-1B] | vLLM |
| [MiniCPM-OCR-1.0] | vLLM |

</details>

`chat_model()` takes the full Hugging Face id, for example `chat_model("rednote-hilab/dots.ocr")`.

## 📚 Reference

<details>
<summary><b>📋 The data model</b></summary>

| Class | Holds |
|---|---|
| `Item` | a book, issue, manuscript or file |
| `Page` | one page: its image and named transcriptions |
| `Transcription` | regions, lines and words with positions, reading order and confidences, plus a [DoclingDocument] |
| `Text` | a whole item's text in one version |

- A page can hold several transcriptions side by side, for example the delivered OCR, a new one and the
  ground truth.
- Positions are pixels of the page image; boxes are `[x, y, width, height]`.
- A `Transcription` survives a round trip through JSON exactly, and through ALTO, PAGE-XML and hOCR
  without losing structure, text, positions or confidences.
- `specs/` has the full design.

</details>

<details>
<summary><b>📖 Text versions</b></summary>

Text moves along three independent axes, one step at a time:

| Axis | From | To |
|---|---|---|
| Characters | as written | normalised, expanded, regularised |
| Flow | as laid out | flowed |
| Scope | full page | body text only |

Named versions:

- `verbatim_txt`: as written, as laid out, full page.
- `readable_txt`, `readable_md`: normalised characters, flowed paragraphs, hyphens joined, body text.

All text is Unicode [NFC]. Normalisation folds long s, ligatures and r rotunda; it keeps æ, œ, ø and ß.
Spelling is never modernised.

</details>

<details>
<summary><b>🎯 Why results are the same everywhere</b></summary>

- Models batch only the lines of one page, in a fixed order. Pages are never mixed.
- Model revisions are pinned. Numerically relevant library versions are fixed per engine environment.
- So a page's output depends on the page and the models, not on the machine, the number of GPUs or what
  else is running.
- Different GPU types can still differ in the last digits of their arithmetic, which causes rare
  one-character differences.

</details>

<details>
<summary><b>🔁 Long runs in stages</b></summary>

- Each stage reads the page rows the last one wrote (`PageRowReader`), adds one part and writes
  complete rows again.
- Originals are never changed.
- A check step (`ValidatePages`, `RejectSink`) sends failed pages to `rejects/` with the reason.
- datatrove keeps logs and completion markers in `logs/`, so finished tasks are skipped on a rerun.

</details>

<details>
<summary><b>🧭 Design principles</b></summary>

- **Every step is replaceable.** Steps share a data model and nothing else.
- **Deployment is not part of the pipeline.** Executors and backends change; steps do not.
- **The text as written is kept.** Readable versions are derived from it and stored next to it.
- **The core stays light.** No machine-learning libraries in the core; engines are separate packages
  with their own environments.
- **Connectors stay generic.** Folders, buckets and Hugging Face datasets. Collection-specific adapters
  belong in the projects that use Linecaster.
- **Open formats out.** ALTO, PAGE-XML, hOCR, text, Markdown, HTML, DocLang, DoclingDocument.

</details>

<details>
<summary><b>🛠️ Extending Linecaster</b></summary>

| To add | Write |
|---|---|
| an engine model | a class with `step`, `name`, `load()` and `__call__(image, transcription)`, packaged under `backends/` |
| a vision-language model | a `ChatModel` subclass (model id, revision, sampling, server flags, request, parsing), registered in `linecaster.models` |
| a processing step | a `PageStep` with `process_page(doc, page)` |

An engine model runs both inside the pipeline and behind `linecaster serve` without further work.

</details>

<details>
<summary><b>🗂️ Repository layout</b></summary>

| Folder | Contents |
|---|---|
| `src/linecaster/` | data model, blocks, server, model specs, executors |
| `backends/` | engine packages: [kraken], [PaddleX] |
| `envs/` | environments with several engines |
| `examples/` | local pipelines |
| `recipes/` | [Ray] and [Hugging Face Jobs][HF Jobs] |
| `specs/` | design of the data model |
| `docs/` | images for this README |

</details>

## 📄 Licence

The code is Apache-2.0, see [LICENSE](LICENSE).

<details>
<summary><b>🖼️ Image credit</b></summary>

The drawing of the linecaster is by Sebastian Majstorovic, made with Adobe Illustrator and Google
Gemini. It is based on a photograph of the
[Intertype C4 Linecaster](https://collection.sciencemuseumgroup.org.uk/objects/co8407592/intertype-c4-linecaster)
(Intertype Ltd, Slough, 1961; object Y1990.104.12, gift of M.H. Whittaker & Son) in the Science
Museum Group Collection. Photograph © The Board of Trustees of the Science Museum, released under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). The photograph was redrawn as a
black-and-white line drawing.

The drawing is an adaptation of that photograph and is licensed under the same terms,
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). It may not be used for
commercial purposes. The Apache-2.0 licence of the code does not apply to it. The same credit is in
[docs/LICENSE-linecaster-image.md](docs/LICENSE-linecaster-image.md).

</details>

<!-- links -->
[kraken]: https://github.com/mittagessen/kraken
[PaddleX]: https://github.com/PaddlePaddle/PaddleX
[datatrove]: https://github.com/huggingface/datatrove
[saturate]: https://github.com/davanstrien/saturate
[Ray]: https://www.ray.io/
[HF Jobs]: https://huggingface.co/docs/huggingface_hub/guides/jobs
[vLLM]: https://github.com/vllm-project/vllm
[SGLang]: https://github.com/sgl-project/sglang
[Docling]: https://github.com/docling-project/docling
[DoclingDocument]: https://docling-project.github.io/docling/concepts/docling_document/
[ALTO]: https://www.loc.gov/standards/alto/
[PAGE-XML]: https://github.com/PRImA-Research-Lab/PAGE-XML
[hOCR]: https://kba.github.io/hocr-spec/1.2/
[JSON Lines]: https://jsonlines.org/
[Parquet]: https://parquet.apache.org/
[NFC]: https://unicode.org/reports/tr15/
[bhl-ocr-eval]: https://github.com/finebooks/bhl-ocr-eval
[PP-DocLayoutV3]: https://huggingface.co/PaddlePaddle/PP-DocLayoutV3
[PP-DocLayout_plus-L]: https://huggingface.co/PaddlePaddle/PP-DocLayout_plus-L
[PP-OCRv6_tiny_det]: https://huggingface.co/PaddlePaddle/PP-OCRv6_tiny_det
[PP-OCRv6_small_det]: https://huggingface.co/PaddlePaddle/PP-OCRv6_small_det
[PP-OCRv6_medium_det]: https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_det
[kraken-tiny]: https://huggingface.co/small-models-for-glam/kraken-ppocrv6-tiny
[kraken-small]: https://huggingface.co/small-models-for-glam/kraken-ppocrv6-small
[kraken-medium]: https://huggingface.co/small-models-for-glam/kraken-ppocrv6-medium
[SLANet_plus]: https://huggingface.co/PaddlePaddle/SLANet_plus
[PP-LCNet_x1_0_table_cls]: https://huggingface.co/PaddlePaddle/PP-LCNet_x1_0_table_cls
[RT-DETR-L_wired_table_cell_det]: https://huggingface.co/PaddlePaddle/RT-DETR-L_wired_table_cell_det
[RT-DETR-L_wireless_table_cell_det]: https://huggingface.co/PaddlePaddle/RT-DETR-L_wireless_table_cell_det
[PP-FormulaNet_plus-L]: https://huggingface.co/PaddlePaddle/PP-FormulaNet_plus-L
[PP-FormulaNet-L]: https://huggingface.co/PaddlePaddle/PP-FormulaNet-L
[olmOCR-2-7B-1025-FP8]: https://huggingface.co/allenai/olmOCR-2-7B-1025-FP8
[OvisOCR2]: https://huggingface.co/ATH-MaaS/OvisOCR2
[OvisOCR3]: https://huggingface.co/ATH-MaaS/OvisOCR3
[Qianfan-OCR]: https://huggingface.co/baidu/Qianfan-OCR
[Unlimited-OCR]: https://huggingface.co/baidu/Unlimited-OCR
[Unlimited-OCR-2]: https://huggingface.co/baidu/Unlimited-OCR-2
[chandra-ocr-2]: https://huggingface.co/datalab-to/chandra-ocr-2
[DeepSeek-OCR]: https://huggingface.co/deepseek-ai/DeepSeek-OCR
[DeepSeek-OCR-2]: https://huggingface.co/deepseek-ai/DeepSeek-OCR-2
[SmolDocling-256M-preview]: https://huggingface.co/docling-project/SmolDocling-256M-preview
[LightOnOCR-2-1B]: https://huggingface.co/lightonai/LightOnOCR-2-1B
[LightOnOCR-3-0.8B]: https://huggingface.co/lightonai/LightOnOCR-3-0.8B
[LightOnOCR-3-4B]: https://huggingface.co/lightonai/LightOnOCR-3-4B
[Nemotron-3.5-Parse]: https://huggingface.co/nvidia/Nemotron-3.5-Parse
[MiniCPM-OCR-1.0]: https://huggingface.co/openbmb/MiniCPM-OCR-1.0
[PaddleOCR-VL-1.6]: https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6
[Qwen3.5-9B]: https://huggingface.co/Qwen/Qwen3.5-9B
[dots.mocr]: https://huggingface.co/dots-studio/dots.mocr
[dots.ocr]: https://huggingface.co/dots-studio/dots.ocr
[GLM-OCR]: https://huggingface.co/zai-org/GLM-OCR
