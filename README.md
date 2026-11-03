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

Two recipes cover the two ways to read a page. Both write a row per page to `out/rows`, and `--files`
adds ALTO, PAGE-XML, hOCR, text and Markdown.

> [!NOTE]
> Each recipe is a self-contained [uv script][uv scripts]: a `# /// script` block at the top lists
> what it needs, with pinned versions, and a `.lock` file sits next to it. `uv run` installs it on the
> first run; the models download on first use.

### 🤖 A vision-language model reads each page

Needs an NVIDIA GPU and the `vllm` command of [vLLM] on the PATH.

```bash
uv run recipes/vlm.py scans/ out/ \
  --vlm lightonai/LightOnOCR-2-1B
```

Any of the [vision-language models](#-vision-language-models) works; `--regions` has it read each
layout region instead of the whole page.

### 🧱 A chain of smaller models

Layout, line detection and a line recogniser, then post-processing into a document.

```bash
uv run recipes/chain.py scans/ out/ \
  --files out/files --formats md,alto
```

The defaults are PP-DocLayoutV3, PP-OCRv6 lines and kraken; `--recognizer paddlex` or
`--recognizer tesseract` swaps the [line recogniser](#%EF%B8%8F-line-recognisers).

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

Save it in `recipes/` with the `# /// script` block of `recipes/chain.py` at the top, which brings the
engines, and `uv run` it. Built with `linecaster.run.main`, as the recipes are, it gets their command
line for every machine.

> [!TIP]
> The two kinds mix: a `LayoutStep` followed by `ChatRegionStep` has a vision-language model read
> each layout region, which is what `recipes/vlm.py --regions` does.

## 🧩 How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture-dark.svg">
  <img src="docs/architecture-light.svg" width="760" alt="One page through a linecaster pipeline: page images are read, then layout, line detection, line assignment, recognition, tables, Unicode and typography and document assembly each add a part to the page's Transcription. The four model steps send the page through saturate to linecaster serve on a GPU and get it back with their part added. Pages with errors go to rejects; the rest are written as page rows, ALTO, PAGE, hOCR, text and Markdown. The executor runs many copies of this task.">
</picture>

*The path of one page through a chain of smaller models. Shaded steps run a model. A vision-language
page model takes the place of layout, lines and recognition; a region model takes the place of lines
and recognition.*

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

A recipe runs on every machine with the same steps. Only its flags change:

| Where | Flags |
|---|---|
| 💻 This machine | none: the models load inside the pipeline |
| 🖥️ This machine, with a server | `--backend served` |
| 🧮 A Ray cluster | `--on ray --tasks 64` |
| ☁️ Hugging Face Jobs | `--on hf-jobs --commit <sha>` |

On Ray and HF Jobs every task gets one GPU and starts its own model server on it.

<details>
<summary><b>🖥️ A model server that stays up</b></summary>

`serve` starts `linecaster serve` with the recipe's models and keeps them loaded; `--endpoint` points
runs at it:

```bash
uv run recipes/chain.py serve
uv run recipes/chain.py scans/ out/ \
  --endpoint http://127.0.0.1:8100/v1
```

For a vision-language model, `--vlm-endpoint` points `recipes/vlm.py` at a running vLLM or SGLang. The
servers listen on loopback only.

</details>

<details>
<summary><b>🧮 On every GPU, with Ray</b></summary>

`ray` runs Ray's own command line with the recipe's packages, so every machine has the same Ray and
Linecaster:

```bash
R=recipes/chain.py
uv run $R ray start --head --num-gpus 8
# on each other machine:
# uv run $R ray start --address=<head>:6379
uv run $R scans/ out/ --on ray --tasks 64
```

Images and output must be on storage every machine can reach.

</details>

<details>
<summary><b>☁️ On Hugging Face Jobs</b></summary>

One Job per task, one GPU per Job. Each Job installs Linecaster at a pushed commit, with the engines,
sources and pins of the recipe's `# /// script` block:

```bash
uv run recipes/chain.py \
  hf://datasets/<ns>/<images> \
  hf://buckets/<ns>/<bucket>/<run> \
  --on hf-jobs --commit <sha> --tasks 64
```

`--flavor l4x4 --gpus 4` runs four tasks per Job, one per GPU. `recipes/vlm.py` picks the server image
its model was checked with; `--image` names another. `--dry-run` prints the plan and launches nothing.

</details>

<details>
<summary><b>🧱 What the flags do, for your own pipeline</b></summary>

- **Backends:** `InProcess("module:Class", **kwargs)` loads a model inside the pipeline;
  `Served(endpoint, name)` sends pages to a server through [saturate].
- **Server blocks** start a server inside each task and go last in the pipeline, so the server lives
  until every page is written: `ServeChatModel(spec)` starts [vLLM] or [SGLang],
  `ServeModels(MODELS, script=...)` a recipe's `serve`.
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

`linecaster.run` puts these together for the recipes.

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

## 🧰 Supported models and blocks

Every model belongs to one step. Vision-language models run behind [vLLM] or [SGLang]. The other models
run inside the pipeline or behind `linecaster serve`. They come in one package per engine:
`linecaster-kraken` ([kraken]), `linecaster-paddlex` ([PaddleX]) and `linecaster-tesseract`
([Tesseract]).

### 🤖 Vision-language models

`ChatPageStep` sends the whole page; `ChatRegionStep` sends one crop per layout region. Each spec pins
the model revision. Its settings come from the drivers of the open [bhl-ocr-eval] benchmark, which
follow the models' own instructions. `chat_model()` takes the full Hugging Face id, for example
`chat_model("rednote-hilab/dots.ocr")`.

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

### 🗺️ Layout

`LayoutStep` finds the regions of a page (text blocks, headings, tables, pictures, page numbers) and
their reading order.

| Model | What it gives |
|---|---|
| [PP-DocLayoutV3] | regions as polygons, learned reading order (default) |
| [PP-DocLayout_plus-L] | regions as boxes, reading order from their positions |
| none: `SingleRegionLayout` | the whole page as one text region |

### 📏 Lines

`LinesStep` finds the text lines on the page; `AssignLinesToRegions` puts each into its region, in
reading order.

| Model | Default |
|---|---|
| [PP-OCRv6 tiny][PP-OCRv6_tiny_det] | |
| [PP-OCRv6 small][PP-OCRv6_small_det] | |
| [PP-OCRv6 medium][PP-OCRv6_medium_det] | ✅ |

### 👁️ Line recognisers

`RecognitionStep` reads each line a line detector found and places every word on the page. Three
engines can do it.

**[kraken]**, on torch, from `linecaster-kraken`:

| Model | Default |
|---|---|
| [kraken PP-OCRv6 tiny][kraken-tiny] | |
| [kraken PP-OCRv6 small][kraken-small] | |
| [kraken PP-OCRv6 medium][kraken-medium] | ✅ |
| any kraken model file | |

**[PaddleX]**, on ONNX Runtime, from `linecaster-paddlex`: PaddleOCR's own recognisers.

| Model | Default |
|---|---|
| [PP-OCRv6 tiny][PP-OCRv6_tiny_rec] | |
| [PP-OCRv6 small][PP-OCRv6_small_rec] | |
| [PP-OCRv6 medium][PP-OCRv6_medium_rec] | ✅ |

**[Tesseract]** 5.5, on the CPU, through [tesserocr], from `linecaster-tesseract`: any of Tesseract's
languages and scripts, such as `eng`, `deu+lat` or `script/Latin`.

| Model | Default |
|---|---|
| [tessdata_best] | ✅ |
| [tessdata_fast] | |

`recipes/chain.py` brings all three engines.

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
- Model revisions are pinned. Numerically relevant library versions are pinned in each recipe.
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
  that a recipe installs when it needs them.
- **Connectors stay generic.** Folders, buckets and Hugging Face datasets. Collection-specific adapters
  belong in the projects that use Linecaster.
- **Open formats out.** ALTO, PAGE-XML, hOCR, text, Markdown, HTML, DocLang, DoclingDocument.

</details>

<details>
<summary><b>🛠️ Extending Linecaster</b></summary>

| To add | Write |
|---|---|
| a vision-language model | a `ChatModel` subclass (model id, revision, sampling, server flags, request, parsing), registered in `linecaster.models` |
| another model | a class with `step`, `name`, `load()` and `__call__(image, transcription)`, packaged under `engines/` |
| a processing step | a `PageStep` with `process_page(doc, page)` |

Such a model runs both inside the pipeline and behind `linecaster serve` without further work.

</details>

<details>
<summary><b>🗂️ Repository layout</b></summary>

| Folder | Contents |
|---|---|
| `src/linecaster/` | data model, blocks, server, model specs, executors |
| `engines/` | engine packages: [kraken], [PaddleX], [Tesseract] |
| `recipes/` | self-contained pipelines that run anywhere and serve their models |
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
[PP-OCRv6_tiny_rec]: https://huggingface.co/PaddlePaddle/PP-OCRv6_tiny_rec
[PP-OCRv6_small_rec]: https://huggingface.co/PaddlePaddle/PP-OCRv6_small_rec
[PP-OCRv6_medium_rec]: https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_rec
[Tesseract]: https://github.com/tesseract-ocr/tesseract
[tesserocr]: https://github.com/sirfz/tesserocr
[tessdata_best]: https://github.com/tesseract-ocr/tessdata_best
[tessdata_fast]: https://github.com/tesseract-ocr/tessdata_fast
[uv scripts]: https://docs.astral.sh/uv/guides/scripts/
