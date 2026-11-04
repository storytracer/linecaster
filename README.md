# Linecaster

### Modular OCR pipelines you can run anywhere

<p align="center">
  <img src="docs/linecaster.png" alt="Line drawing of an Intertype C4 linecaster, a hot-metal typesetting machine" width="353">
</p>
<p align="center"><sub>An Intertype C4 linecaster (1961). Drawing after a photograph in the Science
Museum Group Collection, CC BY-NC-SA 4.0. <a href="#-licence">Credit</a></sub></p>

Build an OCR pipeline from interchangeable parts: a model that reads the text, either a vision-language
model or a line recogniser, combined with layout, table and formula models and post-processing. Run
the same pipeline on a laptop, a GPU server, a cluster or [Hugging Face Jobs][HF Jobs].

**Jump to:** [Why](#-why-linecaster) · [Quick start](#-quick-start) · [How it works](#-how-it-works) ·
[Run anywhere](#-run-it-anywhere) · [Outputs](#-what-you-get) ·
[Models and blocks](#-supported-models-and-blocks) · [Reference](#-reference)

## 🤔 Why Linecaster

Turning a scan into usable text takes more than one model. The text has to be read, by a
vision-language model or by a line recogniser. Around that, the layout has to be found, tables and
formulas rebuilt, and the text cleaned, reflowed and written in the formats people use. Every model
comes with its own software, and every machine has its own way of starting and scaling work. Swapping
a model or moving to bigger hardware usually means starting over.

Linecaster keeps the parts and the machines apart:

- 🧩 **Any component.** Reading, layout, lines, tables, formulas and post-processing are separate
  steps. Use a [vision-language model](#-vision-language-models) on whole pages or on layout regions,
  or a [line recogniser](#%EF%B8%8F-line-recognisers) with a line detector, and add any of the other steps.
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
```

The quickest start is `launch.py` with a name: a **recipe** (a tested combination of models) or a
**model** that reads whole pages. It knows which pipeline that needs. For your own combination, fill a
pipeline's slots yourself, one preset per step. Either way you get a row per page in `out/rows`, and
`--files` adds ALTO, PAGE-XML, hOCR, text and Markdown.

```bash
uv run launch.py squiddle scans/ out/          # a recipe
uv run launch.py lightonocr-2-1b scans/ out/   # a model
uv run launch.py                               # lists the recipes and models
```

Every pipeline option works after the name, e.g. `--on hf-jobs` or `--text lines`.

> [!NOTE]
> Each pipeline is a self-contained [uv script][uv scripts]: a `# /// script` block at the top lists
> what it needs, with pinned versions, and a `.lock` file sits next to it. `uv run` installs it on the
> first run; the models download on first use.

### 🍳 A recipe

A recipe is a named combination: a pipeline, a preset edition for each step, and its options, with its own
edition, provenance and evidence. SquiddleOCR's is `squiddle`:

```bash
uv run launch.py squiddle scans/ out/
```

Options after the name change single steps or settings; the run record lists them as overrides.

### 🤖 A vision-language model reads each page

Needs an NVIDIA GPU and the `vllm` command of [vLLM] on the PATH.

```bash
uv run launch.py lightonocr-2-1b scans/ out/
```

Any [model for whole pages](#-models-and-blocks) works. A region model reads each layout region instead,
in the `vlm` pipeline with a layout preset:
`uv run pipelines/vlm.py scans/ out/ --layout pp-doclayoutv3 --vlm minicpm-ocr-1.0`.

### 🧱 A chain of smaller models

Layout, line detection and a line recogniser, then post-processing into a document. You pick each
step's preset; `linecaster models` lists them.

```bash
uv run pipelines/chain.py scans/ out/ \
  --layout pp-doclayoutv3 \
  --lines pp-ocrv6-medium-det \
  --recognizer kraken-ppocrv6-medium \
  --files out/files --formats md,alto
```

Without `--layout` the page is one region; `--tables` and `--formulas` add those steps.
`--set recognition.batch_size=4` changes one option of a preset.

### ✍️ Your own pipeline

A pipeline is a list of blocks. This is the chain above, cut down:

```python
from datatrove.executor import LocalPipelineExecutor
from linecaster.backends import InProcess as P
from linecaster.blocks.document import (
    AssembleDocument, Typography)
from linecaster.blocks.lines import AssignLinesToRegions
from linecaster.blocks.models import (
    LayoutStep, LinesStep, RecognitionStep)
from linecaster.blocks.readers import ImageFolderReader
from linecaster.blocks.unicode import NormalizeUnicode
from linecaster.blocks.writers import PageFilesWriter

pipeline = [
    ImageFolderReader("scans/"),
    LayoutStep(P("linecaster_paddlex:PaddleLayoutModel")),
    LinesStep(P("linecaster_paddlex:PaddleLineModel")),
    AssignLinesToRegions(),
    RecognitionStep(
        P("linecaster_kraken:KrakenRecognitionModel")),
    NormalizeUnicode(),
    Typography(),
    AssembleDocument(),
    PageFilesWriter("out/", formats=("md", "alto")),
]
LocalPipelineExecutor(
    pipeline, logging_dir="out/logs").run()
```

Save it in `pipelines/` with the `# /// script` block of `pipelines/chain.py` at the top, which brings the
engines, and `uv run` it. Built with `linecaster.run.main`, as the pipelines are, it gets their command
line for every machine.

> [!TIP]
> The two kinds mix: a `LayoutStep` followed by `ChatRegionStep` has a vision-language model read
> each layout region, which is what `pipelines/vlm.py --layout …` does.

## 🧩 How it works

Three ideas carry the design:

1. 📋 **One record per page.** Every step reads the page's `Transcription` and adds its part: regions,
   lines, text, tables, a document. Steps never talk to each other, so any step can be replaced.
2. 🔌 **Each model step has a backend.** `InProcess` loads the model inside the pipeline. `Served` sends
   pages to a model server through [saturate], which keeps enough pages in flight that the GPU never
   waits.
3. 🏗️ **The executor decides where it runs.** Pipelines are [datatrove] pipelines. Executors split the
   pages into tasks, run them locally, on a [Ray] cluster or on [Hugging Face Jobs][HF Jobs], and resume
   where a run stopped.

## 🌍 Run it anywhere

A pipeline runs on every machine with the same steps. Only its flags change:

| Where | Flags |
|---|---|
| 💻 This machine | none: the models load inside the pipeline |
| 🖥️ This machine, with a server | `--backend served` |
| 🧮 A Ray cluster | `--on ray --tasks 64` |
| ☁️ Hugging Face Jobs | `--on hf-jobs --commit <sha>` |

On Ray and HF Jobs every task gets one GPU and starts its own model server on it.

<details>
<summary><b>🖥️ A model server that stays up</b></summary>

`serve` starts `linecaster serve` with the presets you name and keeps them loaded; `--endpoint` points
runs at it:

```bash
P="--layout pp-doclayoutv3
   --lines pp-ocrv6-medium-det
   --recognizer kraken-ppocrv6-medium"
uv run pipelines/chain.py serve $P
uv run pipelines/chain.py scans/ out/ $P \
  --endpoint http://127.0.0.1:8100/v1
```

For a vision-language model, `--vlm-endpoint` points `pipelines/vlm.py` at a running vLLM or SGLang. The
servers listen on loopback only.

</details>

<details>
<summary><b>🧮 On every GPU, with Ray</b></summary>

`ray` runs Ray's own command line with the pipeline's packages, so every machine has the same Ray and
Linecaster (`$P`: the presets, as above):

```bash
R=pipelines/chain.py
uv run $R ray start --head --num-gpus 8
# on each other machine:
# uv run $R ray start --address=<head>:6379
uv run $R scans/ out/ $P --on ray --tasks 64
```

Images and output must be on storage every machine can reach.

</details>

<details>
<summary><b>☁️ On Hugging Face Jobs</b></summary>

One Job per task, one GPU per Job. Each Job installs Linecaster at a pushed commit, with the engines,
sources and pins of the pipeline's `# /// script` block:

```bash
uv run pipelines/chain.py \
  hf://datasets/<ns>/<images> \
  hf://buckets/<ns>/<bucket>/<run> $P \
  --on hf-jobs --commit <sha> --tasks 64
```

`--flavor l4x4 --gpus 4` runs four tasks per Job, one per GPU. `pipelines/vlm.py` picks the server image
its model was checked with; `--image` names another. `--dry-run` prints the plan and launches nothing.

</details>

<details>
<summary><b>🧱 What the flags do, for your own pipeline</b></summary>

- **Backends:** `InProcess("module:Class", **kwargs)` loads a model inside the pipeline;
  `Served(endpoint, name)` sends pages to a server through [saturate].
- **Server blocks** start a server inside each task and go last in the pipeline, so the server lives
  until every page is written: `ServeChatModel(spec)` starts [vLLM] or [SGLang],
  `ServeModels(MODELS, script=...)` a pipeline's `serve`.
- **Executors:** `LocalPipelineExecutor`, `RayGPUExecutor`, and on HF Jobs `JobsPipelineExecutor` or
  `GPUJobsExecutor` with `dependencies(commit, script)`, which turns a script's `# /// script` block
  into what each Job installs.

`MODELS` names the models a server hosts:

```python
MODELS = [
    {"name": "layout",
     "spec": "linecaster_paddlex:PaddleLayoutModel"},
    {"name": "recognition",
     "spec": "linecaster_kraken:KrakenRecognitionModel",
     "kwargs": {"model": "medium"}},
]
```

`linecaster.run` puts these together for the pipelines.

</details>

## 📦 What you get

| Output | What it is for |
|---|---|
| 📜 Text as printed | checking against a hand-made transcription |
| 📖 Readable text | reading and training: old letterforms folded, hyphens joined, paragraphs flowed |
| 📝 Markdown, HTML, DocLang, [Docling] JSON | documents with headings, tables and formulas |
| 🏛️ [ALTO], [PAGE-XML], [hOCR] | libraries and viewers: every word with its position |
| 🗂️ Page rows ([JSON Lines], [Parquet]) | later pipelines: every intermediate result |

Files come per page or, for a book, one per version. Word positions need a model that gives them,
such as a line recogniser.

## 🧰 Models and blocks

Every model is a **preset** in Linecaster's catalogue: one engine, one model at a pinned revision, and its
settings. The original model card is copied next to it, unchanged, at exactly that revision.
`linecaster models` lists the presets; [docs/catalog](docs/catalog/README.md) has a page for each
engine, model, preset, pipeline and recipe, with the results and where every number comes from.

Vision-language models run behind [vLLM] or [SGLang]. The other models run inside the pipeline or behind
`linecaster serve`, one package per engine: `linecaster-kraken` ([kraken]), `linecaster-paddlex`
([PaddleX]) and `linecaster-tesseract` ([Tesseract]).

<!-- catalog:start -->
### 🗺️ Layout

| Preset | Model |
|---|---|
| [`pp-doclayout-plus-l`](docs/catalog/presets/layout/pp-doclayout-plus-l.md) | [PP-DocLayout_plus-L](https://huggingface.co/PaddlePaddle/PP-DocLayout_plus-L_onnx/tree/feb74619326f634e0e883218598096a3733ad9f7) |
| [`pp-doclayoutv3`](docs/catalog/presets/layout/pp-doclayoutv3.md) | [PP-DocLayoutV3](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_onnx/tree/46bbdf188bb0a772c08aed74882ce7e51a8f1ea6) |

### 📏 Lines

| Preset | Model |
|---|---|
| [`pp-ocrv6-medium-det`](docs/catalog/presets/lines/pp-ocrv6-medium-det.md) | [PP-OCRv6_medium_det](https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_det_onnx/tree/61323801669c338b7891481ec7bac61ce31b576a) |
| [`pp-ocrv6-small-det`](docs/catalog/presets/lines/pp-ocrv6-small-det.md) | [PP-OCRv6_small_det](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_det_onnx/tree/28fe5895c24fd108c19eb3e8479f4ab385fbfc62) |
| [`pp-ocrv6-tiny-det`](docs/catalog/presets/lines/pp-ocrv6-tiny-det.md) | [PP-OCRv6_tiny_det](https://huggingface.co/PaddlePaddle/PP-OCRv6_tiny_det_onnx/tree/2ba1506c0380b8f0b03dd142459aac66d4421f6c) |

### 👁️ Recognition

| Preset | Model |
|---|---|
| [`kraken-ppocrv6-medium`](docs/catalog/presets/recognition/kraken-ppocrv6-medium.md) | [PP-OCRv6 (medium)](https://huggingface.co/small-models-for-glam/kraken-ppocrv6-medium/tree/f7fd70f3fd22b615f41bada4674ac2462f938339) |
| [`kraken-ppocrv6-small`](docs/catalog/presets/recognition/kraken-ppocrv6-small.md) | [PP-OCRv6 (small)](https://huggingface.co/small-models-for-glam/kraken-ppocrv6-small/tree/49c249bf81d95ab2c5f699638d066f7935da6f16) |
| [`kraken-ppocrv6-tiny`](docs/catalog/presets/recognition/kraken-ppocrv6-tiny.md) | [PP-OCRv6 (tiny)](https://huggingface.co/small-models-for-glam/kraken-ppocrv6-tiny/tree/045d350d5a7664054370539b87bab0e790724ee2) |
| [`lightonocr-2-1b-regions`](docs/catalog/presets/recognition/lightonocr-2-1b-regions.md) | [LightOnOCR-2-1B](https://huggingface.co/lightonai/LightOnOCR-2-1B/tree/c97bd377f04481830395218fa8951df9deaba756) |
| [`minicpm-ocr-1.0`](docs/catalog/presets/recognition/minicpm-ocr-1.0.md) | [MiniCPM-OCR 1.0](https://huggingface.co/openbmb/MiniCPM-OCR-1.0/tree/a59a4acf215e34c6d73149e9eafdb88ed2086e39) |
| [`paddlex-ppocrv6-medium`](docs/catalog/presets/recognition/paddlex-ppocrv6-medium.md) | [PP-OCRv6_medium_rec](https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_rec_onnx/tree/50c7eacafc52fa7bcf4194e8cd08e46f8558504b) |
| [`paddlex-ppocrv6-small`](docs/catalog/presets/recognition/paddlex-ppocrv6-small.md) | [PP-OCRv6_small_rec](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_rec_onnx/tree/b8f84f0b80c529de40b4fbb3544b84fa7233a513) |
| [`paddlex-ppocrv6-tiny`](docs/catalog/presets/recognition/paddlex-ppocrv6-tiny.md) | [PP-OCRv6_tiny_rec](https://huggingface.co/PaddlePaddle/PP-OCRv6_tiny_rec_onnx/tree/2612ab37152ae0a677521bae4e1e3d4fb4cf7c30) |
| [`tesseract-best-eng`](docs/catalog/presets/recognition/tesseract-best-eng.md) | [tessdata_best](https://github.com/tesseract-ocr/tessdata_best/tree/e12c65a915945e4c28e237a9b52bc4a8f39a0cec) |
| [`tesseract-best-latin`](docs/catalog/presets/recognition/tesseract-best-latin.md) | [tessdata_best](https://github.com/tesseract-ocr/tessdata_best/tree/e12c65a915945e4c28e237a9b52bc4a8f39a0cec) |
| [`tesseract-fast-eng`](docs/catalog/presets/recognition/tesseract-fast-eng.md) | [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast/tree/87416418657359cb625c412a48b6e1d6d41c29bd) |
| [`tesseract-fast-latin`](docs/catalog/presets/recognition/tesseract-fast-latin.md) | [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast/tree/87416418657359cb625c412a48b6e1d6d41c29bd) |

### 📊 Tables

| Preset | Model |
|---|---|
| [`slanet-plus`](docs/catalog/presets/tables/slanet-plus.md) | [SLANet_plus](https://huggingface.co/PaddlePaddle/SLANet_plus_onnx/tree/7dbe640e127602bf506815e822c09758de73c482) |

### ➗ Formulas

| Preset | Model |
|---|---|
| [`pp-formulanet-l`](docs/catalog/presets/formulas/pp-formulanet-l.md) | [PP-FormulaNet-L](https://huggingface.co/PaddlePaddle/PP-FormulaNet-L_safetensors/tree/69869f2891cc61347d230ef234bcc8b8d297c43a) |
| [`pp-formulanet-plus-l`](docs/catalog/presets/formulas/pp-formulanet-plus-l.md) | [PP-FormulaNet_plus-L](https://huggingface.co/PaddlePaddle/PP-FormulaNet_plus-L_safetensors/tree/6cc004a8e91ea3f3819b05317f40b290cbe99c2b) |

### 🤖 Vision-language models, whole pages

| Preset | Model |
|---|---|
| [`chandra-ocr-2`](docs/catalog/presets/page/chandra-ocr-2.md) | [Chandra 2](https://huggingface.co/datalab-to/chandra-ocr-2/tree/af93b47dba1b47b6640c86ccf487ed2260ab9a09) |
| [`deepseek-ocr`](docs/catalog/presets/page/deepseek-ocr.md) | [DeepSeek-OCR](https://huggingface.co/deepseek-ai/DeepSeek-OCR/tree/9f30c71f441d010e5429c532364a86705536c53a) |
| [`deepseek-ocr-2`](docs/catalog/presets/page/deepseek-ocr-2.md) | [DeepSeek-OCR 2](https://huggingface.co/deepseek-ai/DeepSeek-OCR-2/tree/aaa02f3811945a91062062994c5c4a3f4c0af2b0) |
| [`dots-mocr`](docs/catalog/presets/page/dots-mocr.md) | [dots.mocr](https://huggingface.co/rednote-hilab/dots.mocr/tree/e539fbb52280393adc081b289ec597430a0f9031) |
| [`dots-ocr`](docs/catalog/presets/page/dots-ocr.md) | [dots.ocr](https://huggingface.co/rednote-hilab/dots.ocr/tree/c0111ce6bc07803dbc267932ffef0ae3a51dc951) |
| [`glm-ocr`](docs/catalog/presets/page/glm-ocr.md) | [GLM-OCR](https://huggingface.co/zai-org/GLM-OCR/tree/ca5d8b3e287e52589e37c28385d9655ee4372f9d) |
| [`lightonocr-2-1b`](docs/catalog/presets/page/lightonocr-2-1b.md) | [LightOnOCR-2-1B](https://huggingface.co/lightonai/LightOnOCR-2-1B/tree/c97bd377f04481830395218fa8951df9deaba756) |
| [`lightonocr-3-0.8b`](docs/catalog/presets/page/lightonocr-3-0.8b.md) | [LightOnOCR-3-0.8B](https://huggingface.co/lightonai/LightOnOCR-3-0.8B/tree/36d8636925327c671bd8e479c517a004f7566bd9) |
| [`lightonocr-3-4b`](docs/catalog/presets/page/lightonocr-3-4b.md) | [LightOnOCR-3-4B](https://huggingface.co/lightonai/LightOnOCR-3-4B/tree/b71010f095dc3735de7ee6b9969bff8f8f50b39a) |
| [`nemotron-3.5-parse`](docs/catalog/presets/page/nemotron-3.5-parse.md) | [Nemotron 3.5 Parse](https://huggingface.co/nvidia/Nemotron-3.5-Parse/tree/62cb1e4ba153d113ff64aaf2be6e068c377cf53c) |
| [`olmocr-2-7b-1025-fp8`](docs/catalog/presets/page/olmocr-2-7b-1025-fp8.md) | [olmOCR-2-7B-1025-FP8](https://huggingface.co/allenai/olmOCR-2-7B-1025-FP8/tree/40bd7202494b8264ee17ada08b401b5aab7a9ce1) |
| [`ovisocr2`](docs/catalog/presets/page/ovisocr2.md) | [OvisOCR2](https://huggingface.co/ATH-MaaS/OvisOCR2/tree/65c619d374b55d4152e85150fc1b003700bc1f0c) |
| [`ovisocr3`](docs/catalog/presets/page/ovisocr3.md) | [OvisOCR3](https://huggingface.co/ATH-MaaS/OvisOCR3/tree/5f6ce6932efee9ec10c30746db55bd780214b7fd) |
| [`paddleocr-vl-1.6`](docs/catalog/presets/page/paddleocr-vl-1.6.md) | [PaddleOCR-VL-1.6](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/tree/66317acc4c9fc17bd154591ce650735cd2855f3e) |
| [`qianfan-ocr`](docs/catalog/presets/page/qianfan-ocr.md) | [Qianfan-OCR](https://huggingface.co/baidu/Qianfan-OCR/tree/623bf5d20d446abdb36606aa4547cd0c18886fe5) |
| [`qwen3.5-9b`](docs/catalog/presets/page/qwen3.5-9b.md) | [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B/tree/c202236235762e1c871ad0ccb60c8ee5ba337b9a) |
| [`smoldocling-256m-preview`](docs/catalog/presets/page/smoldocling-256m-preview.md) | [SmolDocling-256M-preview](https://huggingface.co/ds4sd/SmolDocling-256M-preview/tree/ce51f56c4ebe36e0b1c3a55f67b261ba22a50bf8) |
| [`unlimited-ocr`](docs/catalog/presets/page/unlimited-ocr.md) | [Unlimited-OCR](https://huggingface.co/baidu/Unlimited-OCR/tree/07dea832e22aefee32ad281d4b80551282e1c168) |
| [`unlimited-ocr-2`](docs/catalog/presets/page/unlimited-ocr-2.md) | [Unlimited-OCR 2](https://huggingface.co/baidu/Unlimited-OCR-2/tree/9cf077c4b206e0e2a31879df937b0b0bcba3661c) |

### 🍳 Recipes

| Recipe | Pipeline | Presets |
|---|---|---|
| [`squiddle`](docs/catalog/recipes/squiddle.md) | `chain.v1` | `pp-doclayoutv3@1`, `pp-ocrv6-medium-det@1`, `kraken-ppocrv6-medium@1`, `slanet-plus@2`, `pp-formulanet-plus-l@1` |
<!-- catalog:end -->

### ✨ Post-processing

These blocks need no model.

| Block | What it does |
|---|---|
| `NormalizeUnicode` | the text in one Unicode form, [NFC] by default |
| `Typography` | heading levels from type size, headlines, drop capitals, uncertain page numbers removed |
| `AssembleDocument` | a [DoclingDocument] per page: lines joined into paragraphs, line-end hyphens removed |
| `AssembleItemDocument` | one DoclingDocument per book, paragraphs continued across pages |
| `ItemTexts` | one text per book in each [text version](#-reference) |

### 📥 Input, output and servers

**Readers**

| Block | What it does |
|---|---|
| `ImageFolderReader` | page images from a folder or bucket |
| `HFImageDatasetReader` | page images from a Hugging Face dataset |
| `PageRowReader` | page rows written by an earlier run |

**Images and checks**

| Block | What it does |
|---|---|
| `AttachImage` | loads a page's image again by its address |
| `WorkingImages` | the image as lossless WebP, size checked |
| `ValidatePages` | sets aside invalid pages, with the reason |

**Writers**

| Block | What it does |
|---|---|
| `PageFilesWriter` | one file per page and format: ALTO, PAGE-XML, hOCR, Markdown, text and more |
| `PageJsonlWriter` | page rows as JSON Lines |
| `PageParquetWriter` | page rows as Parquet |
| `PageExportsWriter` | page documents as Markdown, text, HTML, DocLang, JSON |
| `ItemExportsWriter` | book documents as Markdown, text, HTML, DocLang, JSON |
| `ItemTextJsonlWriter` | book texts as JSON Lines |
| `ItemTextFilesWriter` | book texts as files |

**Servers**

| Block | What it does |
|---|---|
| `ServeChatModel` | starts vLLM or SGLang inside a task |
| `ServeModels` | starts `linecaster serve` inside a task |

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
- Model revisions are pinned. Numerically relevant library versions are pinned in each pipeline script.
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
  that a pipeline installs when it needs them.
- **Connectors stay generic.** Folders, buckets and Hugging Face datasets. Collection-specific adapters
  belong in the projects that use Linecaster.
- **Open formats out.** ALTO, PAGE-XML, hOCR, text, Markdown, HTML, DocLang, DoclingDocument.

</details>

<details>
<summary><b>📚 The catalogue</b></summary>

- **One catalogue**, in `src/linecaster/catalog/data/`: models (`models/<id>/model.md`, with the upstream
  card in `upstream/<revision>/`), presets by step (`presets/<step>/<id>.md`), recipes (`recipes/<id>.md`)
  and evidence records (`evidence/*.yaml`). Model, preset and recipe documents are Markdown with YAML front
  matter: data on top, the reasons below.
- **Code has versioned ids.** A preset names its engine (`engine: kraken.recognition.v1`), a recipe its
  pipeline (`pipeline: chain.v1`). An incompatible change of options is a new id (`.v2`).
- **Versions:** `version` and `revision` are upstream's, verbatim and exact. A preset or recipe has its
  own integer `edition`, referred to as `id@edition`.
- **Released editions don't change.** `catalog.lock` keeps each released edition's functional content
  and its hash, and `linecaster catalog verify` fails when a released edition changes. Old editions stay
  resolvable.
- **Provenance:** each page file names the presets and revisions that made it (ALTO `Processing`,
  PAGE-XML `MetadataItem`, hOCR metas). Each run writes `OUT/run.yaml` with every preset, edition, hash
  and override.
- **Recipes** (`recipes/<id>.md`): a pipeline, a preset edition per slot, options. A recipe's hash covers
  its presets' hashes, so one recipe edition pins everything down to the weights.
- **Evidence** records name their source: a Linecaster run, the BHL board, a model card's claim. A whole
  pipeline's results belong to a recipe; a preset's to the preset, with the rest of the pipeline as context.
- [specs/catalog.md](specs/catalog.md) has the full design.

</details>

<details>
<summary><b>🛠️ Extending Linecaster</b></summary>

| To add | Write |
|---|---|
| a model | `linecaster catalog pin <id> --hf <repo>` for its model document and card, then a preset (`presets/<step>/<id>.md`) and `linecaster catalog release <id>` |
| a vision-language model | the same, with `engine: chat.v1` and an adapter in `linecaster.models.ADAPTERS` if no existing one fits |
| an engine | a class with `engine_id`, `step`, `Options`, `capabilities`, `load()` and `__call__(image, transcription)`, packaged under `engines/` and registered as an entry point (`linecaster.engines`) |
| a recipe | `recipes/<id>.md`: a pipeline id, a preset edition per slot, options; then `linecaster catalog release <id>` |
| a processing step | a `PageStep` with `process_page(doc, page)` |

An engine runs both inside the pipeline and behind `linecaster serve` without further work.

</details>

<details>
<summary><b>🗂️ Repository layout</b></summary>

| Folder | Contents |
|---|---|
| `src/linecaster/` | data model, blocks, server, catalogue, chat adapters, executors |
| `src/linecaster/catalog/data/` | the catalogue: models with their cards, presets by step, recipes, evidence, `catalog.lock` |
| `engines/` | engine packages: [kraken], [PaddleX], [Tesseract] (code only; their presets are in the catalogue) |
| `launch.py` | launches a recipe or a whole-page model by its name, in the pipeline it needs |
| `pipelines/` | self-contained pipelines that run anywhere and serve their models |
| `tools/` | small utilities, e.g. a GPU probe for HF Jobs |
| `specs/` | design of the data model and the catalogue |
| `docs/` | the generated catalogue pages (`docs/catalog/`, one folder per component), images for this README |

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
[PP-OCRv6_tiny_rec]: https://huggingface.co/PaddlePaddle/PP-OCRv6_tiny_rec
[PP-OCRv6_small_rec]: https://huggingface.co/PaddlePaddle/PP-OCRv6_small_rec
[PP-OCRv6_medium_rec]: https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_rec
[Tesseract]: https://github.com/tesseract-ocr/tesseract
[tesserocr]: https://github.com/sirfz/tesserocr
[tessdata_best]: https://github.com/tesseract-ocr/tessdata_best
[tessdata_fast]: https://github.com/tesseract-ocr/tessdata_fast
[uv scripts]: https://docs.astral.sh/uv/guides/scripts/
