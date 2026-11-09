# Linecaster

### Modular OCR pipelines you can run anywhere

<p align="center">
  <img src="docs/linecaster.png" alt="Line drawing of an Intertype C4 linecaster, a hot-metal typesetting machine" width="353">
</p>
<p align="center"><sub>An Intertype C4 linecaster (1961), after a photograph in the Science Museum Group
Collection, CC BY-NC-SA 4.0. <a href="#-license">Credit</a></sub></p>

Linecaster turns page images into text. You build an OCR pipeline from interchangeable steps (a model that
reads the text, layout, tables, formulas, post-processing) and run it unchanged on a laptop, a GPU server, a
Ray cluster or [Hugging Face Jobs][HF Jobs].

- 🧩 **Any step is replaceable.** A vision-language model or a line recognizer reads the text; layout, table
  and formula models and rule-based post-processing are separate steps.
- 🌍 **Any machine.** Only the command line changes, never the pipeline.
- 🎯 **The same result everywhere.** A page's text depends only on that page and the pinned models.
- 🔁 **Built for long runs.** Interrupted runs resume; failed pages are set aside with the reason.

📖 **Docs:** [storytracer.github.io/linecaster](https://storytracer.github.io/linecaster/): the reference, a page
for every block and catalog entry, and [`llms.txt`](https://storytracer.github.io/linecaster/latest/llms.txt) for
coding agents.

## 🚀 Quick start

You need Python 3.12 and [uv](https://docs.astral.sh/uv/) 0.13.6 or newer.

```bash
git clone https://github.com/storytracer/linecaster
cd linecaster
uv run launch.py                               # list the recipes and models
uv run launch.py squiddle scans/ out/          # run a recipe
uv run launch.py lightonocr-2-1b scans/ out/   # run a vision-language model (needs vLLM and a GPU)
```

You get one page record per page in `out/pages/`. Add `--files out/files --formats md,alto` for per-page files.

> [!NOTE]
> Every pipeline is a self-contained [uv script][uv scripts] with pinned dependencies and a lock file next to it.
> `uv run` installs what it needs on the first run; models download on first use.

## 🧭 Three ways to transcribe

**1. A recipe**: a tested combination of presets, one per step, with its own edition and evidence.

```bash
uv run launch.py squiddle scans/ out/
```

**2. A vision-language model** reads each page, or each layout region. It runs behind [vLLM] or [SGLang], so it
needs an NVIDIA GPU and the `vllm` command on the PATH.

```bash
uv run launch.py lightonocr-2-1b scans/ out/
uv run pipelines/transcribe_vlm.py scans/ out/ --layout pp-doclayoutv3 --recognition minicpm-ocr-1.0
```

**3. The modular pipeline**: layout, lines and a line recognizer, then post-processing. You choose a preset for
every step; `linecaster models` lists them.

```bash
uv run pipelines/transcribe_modular.py scans/ out/ \
  --layout pp-doclayoutv3 \
  --lines pp-ocrv6-medium-det \
  --recognition kraken-ppocrv6-medium \
  --typography ratios --recomposition unicode-recomposition --composition docling-composition
```

| Flag | Effect |
|---|---|
| `--layout single-region` | the whole page as one region, no layout model |
| `--tables`, `--formulas` | add table and formula recognition |
| `--typography` | headings and their levels |
| `--recomposition` | running text in paragraphs (without it, the page stays as laid out) |
| `--composition` | the page's document, for Markdown, HTML and JSON |
| `--set recognition.batch_size=4` | change one option of a preset |
| `--files DIR --formats md,alto` | per-page files: ALTO, PAGE-XML, hOCR, text, Markdown, HTML, DocLang, JSON |
| `--dry-run` | print the plan and its graph, run nothing |

Options after a recipe's name override single steps; the run record lists them.

## 📥 Input

| Pages from | Flags |
|---|---|
| a folder of images | `IMAGES` (`--item-from-parent`: each subfolder is an item) |
| a list of images | `IMAGES --paths-file pages.txt` |
| Parquet with an image column | `--parquet PATH` (`--image-key`, `--item-key`, `--sequence-key`) |
| IIIF or METS manifests | `--manifests FOLDER`, `--manifests list.txt`, or `--manifests items.parquet --manifest-key url` |
| an earlier run | `--pages OUT/pages` |

Any fsspec path works: local, `s3://`, `hf://`. Manifests need the `pybookget` extra
([pybookget](https://github.com/storytracer/pybookget)); `--existing-ocr` also keeps the library's own OCR as
`ocr_original`. PDF files are read by the `PdfReader` block (extra `pypdfium2`).

For large collections, fetch the images once, then transcribe, then bind the pages into items:

```bash
uv run pipelines/harvest.py --manifests items.parquet --manifest-key url OUT --rate-limit 5/1
uv run pipelines/transcribe_modular.py --pages OUT/pages OUT2 --recipe squiddle --item-shards 64
uv run pipelines/bind.py OUT2/pages OUT3 --recipe item-texts
```

## 📦 Output

| Output | For |
|---|---|
| 🗂️ Page records ([JSON Lines], [Parquet]) | later pipelines: every intermediate result |
| 🏛️ [ALTO], [PAGE-XML], [hOCR] | libraries and viewers: every word with its position |
| 📝 Markdown, HTML, DocLang, [Docling] JSON | documents with headings, tables and formulas |
| 📜 `verbatim_txt` per item | the text as printed, for checking against a transcription |
| 📖 `readable_txt`, `readable_md` per item | reading and training: letterforms folded, hyphens joined, paragraphs flowed |

The text as written is always kept; readable text is derived from it. All text is Unicode [NFC]; spelling is never
modernized. Rejected pages go to `rejects/` with the reason. Every run is traced with [OpenTelemetry] into
`OUT/traces/` (nothing is sent anywhere unless you set the `OTEL_*` variables), and `linecaster traces OUT` shows
where the time went.

## 🌍 Run anywhere

| Where | Flags |
|---|---|
| 💻 this machine | none: models load inside the pipeline |
| 🖥️ this machine, with a model server | `--backend served` |
| 🧮 a Ray cluster | `--on ray --tasks 64` |
| ☁️ Hugging Face Jobs | `--on hf-jobs --commit <sha>` |

On Ray and HF Jobs every task gets one GPU and starts its own model server. A rerun into the same output folder
runs only the tasks that didn't finish.

<details>
<summary><b>A model server that stays up</b></summary>

```bash
P="--layout pp-doclayoutv3 --lines pp-ocrv6-medium-det --recognition kraken-ppocrv6-medium"
uv run pipelines/transcribe_modular.py serve $P
uv run pipelines/transcribe_modular.py scans/ out/ $P --endpoint http://127.0.0.1:8100/v1
```

For a vision-language model, `--recognition-endpoint` points `transcribe_vlm.py` at a running vLLM or SGLang.
Servers listen on loopback only.

</details>

<details>
<summary><b>Ray</b></summary>

`ray` runs Ray's own command line with the pipeline's packages, so every machine has the same versions:

```bash
uv run pipelines/transcribe_modular.py ray start --head --num-gpus 8
uv run pipelines/transcribe_modular.py scans/ out/ $P --on ray --tasks 64
```

Images and output must be on storage every machine can reach.

</details>

<details>
<summary><b>Hugging Face Jobs</b></summary>

One GPU per Job; each Job installs Linecaster at a pushed commit with the pipeline's pinned dependencies.

```bash
uv run pipelines/transcribe_modular.py s3://bhl-open-data/images hf://buckets/<ns>/<bucket>/<run> $P \
  --paths-file hf://buckets/<ns>/<bucket>/pages.txt --env FSSPEC_S3_ANON=true \
  --on hf-jobs --commit <sha> --tasks 4000 --workers 64
```

`--workers` Jobs run at once. `--flavor l4x4 --gpus 4` runs four tasks per Job. `--dry-run` launches nothing.

</details>

## ✍️ Your own pipeline

A pipeline is a list of blocks; [datatrove] runs it. This is the modular pipeline, cut down:

```python
from datatrove.executor import LocalPipelineExecutor
from linecaster.backends import InProcess as P
from linecaster.blocks.composition import (
    Composer, Recomposer, Typographer)
from linecaster.blocks.layout import LayoutDetector
from linecaster.blocks.lines import (
    LineAssigner, LineDetector)
from linecaster.blocks.readers import ImageFolderReader
from linecaster.blocks.recognition import LineRecognizer
from linecaster.blocks.text import UnicodeNormalizer
from linecaster.blocks.writers import PageFileWriter

pipeline = [
    ImageFolderReader("scans/"),
    LayoutDetector(P("linecaster_paddlex:PaddleLayoutEngine")),
    LineDetector(P("linecaster_paddlex:PaddleLineEngine")),
    LineAssigner(),
    LineRecognizer(
        P("linecaster_kraken:KrakenRecognitionEngine")),
    UnicodeNormalizer(),
    Typographer("ratios@1"),
    Recomposer("unicode-recomposition@1"),
    Composer("docling-composition@1"),
    PageFileWriter("out/", formats=("md", "alto")),
]
LocalPipelineExecutor(
    pipeline, logging_dir="out/logs").run()
```

Every block declares what it reads and adds, so a pipeline is checked before it starts: a recognizer without
lines fails at once, with every problem listed. Put the script in `pipelines/` with the `# /// script` block of
`pipelines/transcribe_modular.py` (it brings the engines) and build it with `linecaster.runtime.run.main` to get
the pipelines' command line on every machine. The [pipelines reference](docs/reference/pipelines.md) covers
backends, partial runs (`--until`, `--after`) and the builder.

## 🧩 How it works

1. **One record per page.** Every step reads the page's `Transcription` and adds its part: regions, lines, text,
   tables, a document. Steps share the data model and nothing else.
2. **Contracts.** Each block declares what it reads, adds, replaces or removes; the builder checks the pipeline
   and draws its graph from them.
3. **Backends.** A model step runs `InProcess`, `Served` (a model server reached through [saturate], which keeps
   the GPU busy) or `Chat` (a vision-language model behind an OpenAI-compatible server).
4. **Executors.** [datatrove] splits the pages into tasks, runs them locally, on [Ray] or on HF Jobs, and resumes
   where a run stopped.

Models batch only the lines of one page, and model revisions and numerically relevant libraries are pinned, so
a page's output never depends on the machine or on what else runs. Different GPU types can still differ in rare
single characters.

## 🧰 Models and blocks

Every configuration is a **preset** in Linecaster's catalog: an engine, a model at a pinned revision with its
original model card, and settings. Released editions never change. Vision-language models run behind vLLM or
SGLang; the other models run inside the pipeline or behind `linecaster serve`, one package per engine:
`linecaster-kraken` ([kraken]), `linecaster-paddlex` ([PaddleX]) and `linecaster-tesseract` ([Tesseract]).

<details>
<summary><b>The presets and recipes</b></summary>

<!-- catalog:start -->
### 🗺️ Layout

| Preset | Model |
|---|---|
| [`pp-doclayout-plus-l`](docs/catalog/presets/layout/pp-doclayout-plus-l.md) | [PP-DocLayout_plus-L](https://huggingface.co/PaddlePaddle/PP-DocLayout_plus-L_onnx/tree/feb74619326f634e0e883218598096a3733ad9f7) |
| [`pp-doclayoutv3`](docs/catalog/presets/layout/pp-doclayoutv3.md) | [PP-DocLayoutV3](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_onnx/tree/46bbdf188bb0a772c08aed74882ce7e51a8f1ea6) |
| [`single-region`](docs/catalog/presets/layout/single-region.md) | - |

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

### 🖼️ Image

| Preset | Model |
|---|---|
| [`working-image`](docs/catalog/presets/image/working-image.md) | - |

### 🔤 Normalization

| Preset | Model |
|---|---|
| [`latin-historic`](docs/catalog/presets/normalization/latin-historic.md) | - |

### 🔠 Typography

| Preset | Model |
|---|---|
| [`ratios`](docs/catalog/presets/typography/ratios.md) | - |

### 📝 Recomposition

| Preset | Model |
|---|---|
| [`unicode-recomposition`](docs/catalog/presets/recomposition/unicode-recomposition.md) | - |

### 📄 Composition

| Preset | Model |
|---|---|
| [`docling-composition`](docs/catalog/presets/composition/docling-composition.md) | - |

### 🤖 Vision-language models, whole pages

| Preset | Model |
|---|---|
| [`chandra-ocr-2`](docs/catalog/presets/recognition/chandra-ocr-2.md) | [Chandra 2](https://huggingface.co/datalab-to/chandra-ocr-2/tree/af93b47dba1b47b6640c86ccf487ed2260ab9a09) |
| [`deepseek-ocr`](docs/catalog/presets/recognition/deepseek-ocr.md) | [DeepSeek-OCR](https://huggingface.co/deepseek-ai/DeepSeek-OCR/tree/9f30c71f441d010e5429c532364a86705536c53a) |
| [`deepseek-ocr-2`](docs/catalog/presets/recognition/deepseek-ocr-2.md) | [DeepSeek-OCR 2](https://huggingface.co/deepseek-ai/DeepSeek-OCR-2/tree/aaa02f3811945a91062062994c5c4a3f4c0af2b0) |
| [`dots-mocr`](docs/catalog/presets/recognition/dots-mocr.md) | [dots.mocr](https://huggingface.co/rednote-hilab/dots.mocr/tree/e539fbb52280393adc081b289ec597430a0f9031) |
| [`dots-ocr`](docs/catalog/presets/recognition/dots-ocr.md) | [dots.ocr](https://huggingface.co/rednote-hilab/dots.ocr/tree/c0111ce6bc07803dbc267932ffef0ae3a51dc951) |
| [`falcon-ocr`](docs/catalog/presets/recognition/falcon-ocr.md) | [Falcon OCR](https://huggingface.co/tiiuae/Falcon-OCR/tree/177110bf36f6fd492428215baf76d0618854bed3) |
| [`glm-ocr`](docs/catalog/presets/recognition/glm-ocr.md) | [GLM-OCR](https://huggingface.co/zai-org/GLM-OCR/tree/ca5d8b3e287e52589e37c28385d9655ee4372f9d) |
| [`indra-ocr`](docs/catalog/presets/recognition/indra-ocr.md) | [Indra OCR](https://huggingface.co/datalab-to/indra-ocr/tree/bd02167fdf2005a19962cc15188f8496a2c87d3b) |
| [`lightonocr-2-1b`](docs/catalog/presets/recognition/lightonocr-2-1b.md) | [LightOnOCR-2-1B](https://huggingface.co/lightonai/LightOnOCR-2-1B/tree/c97bd377f04481830395218fa8951df9deaba756) |
| [`lightonocr-3-0.8b`](docs/catalog/presets/recognition/lightonocr-3-0.8b.md) | [LightOnOCR-3-0.8B](https://huggingface.co/lightonai/LightOnOCR-3-0.8B/tree/36d8636925327c671bd8e479c517a004f7566bd9) |
| [`lightonocr-3-4b`](docs/catalog/presets/recognition/lightonocr-3-4b.md) | [LightOnOCR-3-4B](https://huggingface.co/lightonai/LightOnOCR-3-4B/tree/b71010f095dc3735de7ee6b9969bff8f8f50b39a) |
| [`nemotron-3.5-parse`](docs/catalog/presets/recognition/nemotron-3.5-parse.md) | [Nemotron 3.5 Parse](https://huggingface.co/nvidia/Nemotron-3.5-Parse/tree/62cb1e4ba153d113ff64aaf2be6e068c377cf53c) |
| [`olmocr-2-7b-1025-fp8`](docs/catalog/presets/recognition/olmocr-2-7b-1025-fp8.md) | [olmOCR-2-7B-1025-FP8](https://huggingface.co/allenai/olmOCR-2-7B-1025-FP8/tree/40bd7202494b8264ee17ada08b401b5aab7a9ce1) |
| [`ovisocr2`](docs/catalog/presets/recognition/ovisocr2.md) | [OvisOCR2](https://huggingface.co/ATH-MaaS/OvisOCR2/tree/65c619d374b55d4152e85150fc1b003700bc1f0c) |
| [`ovisocr3`](docs/catalog/presets/recognition/ovisocr3.md) | [OvisOCR3](https://huggingface.co/ATH-MaaS/OvisOCR3/tree/5f6ce6932efee9ec10c30746db55bd780214b7fd) |
| [`oxr-1.0`](docs/catalog/presets/recognition/oxr-1.0.md) | [OXR-1.0](https://huggingface.co/SoMarkAI/OXR-1.0/tree/c708407f9d2b4df658f2543d9132b62bb7221df4) |
| [`paddleocr-vl-1.6`](docs/catalog/presets/recognition/paddleocr-vl-1.6.md) | [PaddleOCR-VL-1.6](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/tree/66317acc4c9fc17bd154591ce650735cd2855f3e) |
| [`qianfan-ocr`](docs/catalog/presets/recognition/qianfan-ocr.md) | [Qianfan-OCR](https://huggingface.co/baidu/Qianfan-OCR/tree/623bf5d20d446abdb36606aa4547cd0c18886fe5) |
| [`qwen3.5-9b`](docs/catalog/presets/recognition/qwen3.5-9b.md) | [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B/tree/c202236235762e1c871ad0ccb60c8ee5ba337b9a) |
| [`smoldocling-256m-preview`](docs/catalog/presets/recognition/smoldocling-256m-preview.md) | [SmolDocling-256M-preview](https://huggingface.co/ds4sd/SmolDocling-256M-preview/tree/ce51f56c4ebe36e0b1c3a55f67b261ba22a50bf8) |
| [`surya-ocr-2.5`](docs/catalog/presets/recognition/surya-ocr-2.5.md) | [Surya OCR 2.5](https://huggingface.co/datalab-to/surya-ocr-2.5/tree/00c843e9cae45611dca0a6dc2c9bbbf2dadaaed3) |
| [`unlimited-ocr`](docs/catalog/presets/recognition/unlimited-ocr.md) | [Unlimited-OCR](https://huggingface.co/baidu/Unlimited-OCR/tree/07dea832e22aefee32ad281d4b80551282e1c168) |
| [`unlimited-ocr-2`](docs/catalog/presets/recognition/unlimited-ocr-2.md) | [Unlimited-OCR 2](https://huggingface.co/baidu/Unlimited-OCR-2/tree/9cf077c4b206e0e2a31879df937b0b0bcba3661c) |

### 🍳 Recipes

| Recipe | Pipeline | Presets |
|---|---|---|
| [`item-texts`](docs/catalog/recipes/item-texts.md) | `bind.v1` | `unicode-recomposition@1`, `latin-historic@1`, `docling-composition@1` |
| [`squiddle`](docs/catalog/recipes/squiddle.md) | `transcribe_modular.v1` | `pp-doclayoutv3@1`, `pp-ocrv6-medium-det@1`, `kraken-ppocrv6-medium@1`, `slanet-plus@2`, `pp-formulanet-plus-l@1`, `ratios@1`, `unicode-recomposition@1`, `latin-historic@1`, `docling-composition@1` |
<!-- catalog:end -->

</details>

<details>
<summary><b>The blocks</b></summary>

<!-- blocks:start -->
| Family | Block | What it does |
|---|---|---|
| Readers | [`ImageFolderReader`](docs/blocks/readers/ImageFolderReader.md) | Reads one page per image file of a folder or bucket. |
| Readers | [`ImageParquetReader`](docs/blocks/readers/ImageParquetReader.md) | Reads one page per row of Parquet files with an image column. |
| Readers | [`ManifestReader`](docs/blocks/readers/ManifestReader.md) | Reads one page per image of each item's manifest: IIIF Presentation 2 or 3, or METS with MODS (also inside an OAI-PMH response). |
| Readers | [`PageRecordReader`](docs/blocks/readers/PageRecordReader.md) | Reads the page records an earlier run wrote (JSON Lines or Parquet), so a pipeline can add one more part. |
| Readers | [`PdfReader`](docs/blocks/readers/PdfReader.md) | Reads one item per PDF file, one page per PDF page in order, each rendered to a lossless WebP image. |
| Readers | [`ResourceReader`](docs/blocks/readers/ResourceReader.md) | Fetches the remote files of items as they are served, one document per resource, one item per task. |
| Layout | [`LayoutDetector`](docs/blocks/layout/LayoutDetector.md) | Detects the layout regions of every page, with their labels and reading order, by a layout engine. |
| Lines | [`LineAssigner`](docs/blocks/lines/LineAssigner.md) | Assigns the lines detected on the whole page to the layout regions and orders them row by row. |
| Lines | [`LineDetector`](docs/blocks/lines/LineDetector.md) | Detects the text lines of every page, with their geometry, by a line detection engine. |
| Recognition | [`FormulaRecognizer`](docs/blocks/recognition/FormulaRecognizer.md) | Recognizes every formula region as LaTeX by a formula engine. |
| Recognition | [`LineRecognizer`](docs/blocks/recognition/LineRecognizer.md) | Recognizes the text of every line by a line recognition engine. |
| Recognition | [`PageRecognizer`](docs/blocks/recognition/PageRecognizer.md) | Recognizes every page with a chat VLM or a page engine, whose output becomes the page's transcription. |
| Recognition | [`RegionRecognizer`](docs/blocks/recognition/RegionRecognizer.md) | Recognizes each layout region of every page with a chat VLM, one request per region crop. |
| Recognition | [`TableRecognizer`](docs/blocks/recognition/TableRecognizer.md) | Recognizes the structure of every table region by a table engine. |
| Conversion | [`ImageConverter`](docs/blocks/conversion/ImageConverter.md) | Converts each page's delivered image into the working image with an image engine and writes it. |
| Conversion | [`ImageFetcher`](docs/blocks/conversion/ImageFetcher.md) | Loads each page's image again from its address, for the blocks that need pixels. |
| Conversion | [`TranscriptionConverter`](docs/blocks/conversion/TranscriptionConverter.md) | Reads the transcription file that comes with each page (ALTO, PAGE-XML, hOCR or plain text) into a named transcription. |
| Text | [`CharacterNormalizer`](docs/blocks/text/CharacterNormalizer.md) | Normalizes the texts of every line, paragraph and table cell by a normalization engine, next to the text as written. |
| Text | [`UnicodeNormalizer`](docs/blocks/text/UnicodeNormalizer.md) | Normalizes the as-written text of every line and word to one Unicode normalization form, NFC by default. |
| Composition | [`Composer`](docs/blocks/composition/Composer.md) | Composes the DoclingDocument of a page or an item by a composition engine. |
| Composition | [`Recomposer`](docs/blocks/composition/Recomposer.md) | Recomposes the running text of a page or an item into paragraphs by a recomposition engine. |
| Composition | [`Typographer`](docs/blocks/composition/Typographer.md) | Determines the typographic hierarchy of every page by a typography engine. |
| Binding | [`Binder`](docs/blocks/binding/Binder.md) | Binds each item's page records, in order, into one item record. |
| Binding | [`Splitter`](docs/blocks/binding/Splitter.md) | Splits each item record into its page records again, in the item's order, with what the item-level blocks added. |
| Validation | [`PageValidator`](docs/blocks/validation/PageValidator.md) | Marks the page records that do not validate against `Page` or lack a required part with an error each. |
| Validation | [`RecipeStamper`](docs/blocks/validation/RecipeStamper.md) | Stamps the recipe edition a run follows on every step of every transcription, of a page or of each page of an item record. |
| Servers | [`ChatModelServer`](docs/blocks/servers/ChatModelServer.md) | Starts a chat VLM server (vLLM or SGLang) inside the task for its `Chat` backends, through saturate's `Engine`. |
| Servers | [`ModelServer`](docs/blocks/servers/ModelServer.md) | Starts `linecaster serve` inside the task for its served model blocks, through saturate's `Engine`. |
| Servers | [`ServiceServer`](docs/blocks/servers/ServiceServer.md) | Starts the service a page engine's preset names inside the task, and stops it when the task's pages are through. |
| Writers | [`ImageFilesWriter`](docs/blocks/writers/ImageFilesWriter.md) | Writes each page's image bytes as they came, one file per page. |
| Writers | [`ItemDocumentWriter`](docs/blocks/writers/ItemDocumentWriter.md) | Writes the document of each item record, one file per format: Markdown, text, HTML, DocLang, JSON. |
| Writers | [`ItemTextWriter`](docs/blocks/writers/ItemTextWriter.md) | Writes the text variants of each item record as JSON Lines or as files. |
| Writers | [`PageFileWriter`](docs/blocks/writers/PageFileWriter.md) | Writes one file per page and format: ALTO, PAGE-XML, hOCR, text, Markdown, HTML, DocLang, JSON and more. |
| Writers | [`PageJsonlWriter`](docs/blocks/writers/PageJsonlWriter.md) | Writes the page records as JSON Lines, one file per task, or into item shards for a later stage. |
| Writers | [`PageParquetWriter`](docs/blocks/writers/PageParquetWriter.md) | Writes the page records as Parquet, one file per task. |
| Writers | [`RejectWriter`](docs/blocks/writers/RejectWriter.md) | Writes every page that carries errors to the task's rejects file and passes every page on. |
| Writers | [`ResourceFilesWriter`](docs/blocks/writers/ResourceFilesWriter.md) | Writes each resource's bytes as they came, one file per resource. |
| Writers | [`ResourceRecordWriter`](docs/blocks/writers/ResourceRecordWriter.md) | Writes each resource's record (`doc.metadata["resource"]`, with its errors) as a JSON line, to `<output_folder>/<rank>.jsonl.gz`: one file per task, a failed resource included (`error`, `errors`). |
| Composites | [`ModularTranscriber`](docs/blocks/composites/ModularTranscriber.md) | Reads a page's lines the modular way: layout, lines on the whole page, line assignment, line recognition. |
<!-- blocks:end -->

</details>

## 📚 Reference

| Topic | Page |
|---|---|
| terms | [glossary](docs/reference/glossary.md) |
| how the parts fit together | [architecture](docs/reference/architecture.md) |
| blocks, contracts, the builder, runs | [pipelines](docs/reference/pipelines.md) |
| `Item`, `Page`, `Transcription`, text variants | [data model](docs/reference/data-model.md) |
| ALTO, PAGE-XML, hOCR | [serialization](docs/reference/serialization.md) |
| presets, recipes, editions, evidence | [catalog](docs/reference/catalog.md) |
| traces | [tracing](docs/reference/tracing.md) |
| what counts as a breaking change | [compatibility](docs/reference/compatibility.md) |
| names, spelling, docstrings | [conventions](docs/reference/conventions.md) |
| every block, engine, model, preset and recipe | [blocks](docs/blocks/README.md), [catalog](docs/catalog/README.md) |

## 🛠️ Development

| To | Run or write |
|---|---|
| test the core | `uv run pytest` (GPU and network tests skip where those are missing; `-n auto` on every core) |
| test an engine package | `uv run tests/test_engines_catalog.py engines/<engine>/tests` |
| regenerate the docs | `uv run linecaster docs` (`--check` in CI) |
| check released catalog editions | `uv run linecaster catalog verify` |
| see or tidy a broker (after a hard kill: `clean --leases`) | `linecaster broker status PATH`, `clean`, `purge` ([broker](docs/reference/broker.md#the-command)) |
| build the docs site | `uv run --group docs mkdocs build --strict` |
| add a model | `linecaster catalog pin <id> --hf <repo>`, a preset in `presets/<step>/`, `linecaster catalog release <id>` |
| add an engine | a package under `engines/` that imports only `linecaster.data` and `linecaster.engines.api`; test it with `linecaster.testing.check_engine` |
| add a block | a `PageBlock` with `process_page(doc, page)` and a `contract()`; test it with `linecaster.testing.check_block` |

The code lives in `src/linecaster/`, the catalog in `src/linecaster/catalog/data/`, the engine packages in
`engines/`, the pipeline scripts in `pipelines/`. Measurements and decisions are in [NOTES.md](NOTES.md).

## 🏷️ Versions

The current release is `v0.1.0`; [CHANGELOG.md](CHANGELOG.md) lists each release's changes, upgrade notes first.
While the version is 0.x, a release may break things without a deprecation period. The
[docs site](https://storytracer.github.io/linecaster/) keeps a version per release, `latest` for the newest, and
`dev` for `main`.

## 📄 License

The code is Apache-2.0, see [LICENSE](LICENSE).

<details>
<summary><b>Image credit</b></summary>

The drawing of the linecaster is by Sebastian Majstorovic, made with Adobe Illustrator and Google Gemini. It is
based on a photograph of the
[Intertype C4 Linecaster](https://collection.sciencemuseumgroup.org.uk/objects/co8407592/intertype-c4-linecaster)
(Intertype Ltd, Slough, 1961; object Y1990.104.12, gift of M.H. Whittaker & Son) in the Science Museum Group
Collection. Photograph © The Board of Trustees of the Science Museum, released under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/), redrawn as a black-and-white line drawing.

The drawing is an adaptation of that photograph and is licensed under the same terms,
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). It may not be used for commercial
purposes. The Apache-2.0 license of the code does not apply to it. The same credit is in
[docs/LICENSE-linecaster-image.md](docs/LICENSE-linecaster-image.md).

</details>

<!-- links -->
[kraken]: https://github.com/mittagessen/kraken
[PaddleX]: https://github.com/PaddlePaddle/PaddleX
[Tesseract]: https://github.com/tesseract-ocr/tesseract
[datatrove]: https://github.com/huggingface/datatrove
[saturate]: https://github.com/davanstrien/saturate
[OpenTelemetry]: https://opentelemetry.io/
[Ray]: https://www.ray.io/
[HF Jobs]: https://huggingface.co/docs/huggingface_hub/guides/jobs
[vLLM]: https://github.com/vllm-project/vllm
[SGLang]: https://github.com/sgl-project/sglang
[Docling]: https://github.com/docling-project/docling
[ALTO]: https://www.loc.gov/standards/alto/
[PAGE-XML]: https://github.com/PRImA-Research-Lab/PAGE-XML
[hOCR]: https://kba.github.io/hocr-spec/1.2/
[JSON Lines]: https://jsonlines.org/
[Parquet]: https://parquet.apache.org/
[NFC]: https://unicode.org/reports/tr15/
[uv scripts]: https://docs.astral.sh/uv/guides/scripts/
