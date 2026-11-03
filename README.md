# linecaster

linecaster turns page images into text. It combines layout, line, text, table and formula models with
post-processing (dehyphenation, reflow, Unicode normalisation) into
[datatrove](https://github.com/huggingface/datatrove) pipelines. The same pipeline runs on a laptop, a
GPU workstation or Hugging Face Jobs.

Status: first working version (November 2026). The API can still change.

## What you get

- **Text as written**, line by line, plus readable variants: long s and ligatures folded, hyphens joined,
  paragraphs flowed across lines and pages.
- **Markdown** with headings, tables and LaTeX formulas.
- **ALTO, PAGE-XML and hOCR** with word coordinates, for libraries and viewers.
- **One row per page** with every intermediate result, so a later pipeline can pick up where an earlier
  one stopped.

## How it works

```
 page images
     │
     ▼
 reader ──▶ layout ──▶ lines ──▶ recognition ──▶ tables ──▶ typography ──▶ document ──▶ writers
              │          │            │             │
              ▼          ▼            ▼             ▼
        ┌──────────────────────────────────────────────┐
        │  linecaster serve  (one GPU, several models) │   ◀── or vLLM for vision-language models
        └──────────────────────────────────────────────┘
```

- **Each step is a datatrove block.** A pipeline is a list of blocks, so any layout model can be
  combined with any line detector and any recogniser.
- **Servers host the models; the pipeline composes the chain.** `linecaster serve` keeps the engine
  models (kraken, PaddleX) loaded on a GPU. The blocks reach it through
  [saturate](https://github.com/davanstrien/saturate), which keeps enough pages in flight that the
  server never waits.
- **Every model also runs in-process.** That is the reference for checking results and the simple way
  to run on a CPU.
- **A page's result depends only on that page.** Pages are never batched together, so a run gives the
  same output whatever else is in flight and on however many machines.

## Install

linecaster needs Python 3.12 and [uv](https://docs.astral.sh/uv/) 0.13.6 or newer.

```bash
git clone https://github.com/storytracer/linecaster && cd linecaster
uv sync                                  # the core: data model, blocks, serve, Jobs helpers
(cd envs/kraken-paddlex && uv sync)      # the kraken and PaddleX engines, with torch for CUDA 13
```

The core has no machine-learning dependencies. The engines live in their own environment under `envs/`,
because their pins conflict with each other's and with vLLM's.

## Quick start

**The squiddle chain in-process** (PP-DocLayoutV3 layout, PP-OCRv6 line detection, kraken's PP-OCRv6
recogniser, PaddleX tables and formulas):

```bash
envs/kraken-paddlex/.venv/bin/python examples/squiddle_chain.py IMAGES OUT --backend in-process
```

**The same chain against a model server:**

```bash
envs/kraken-paddlex/.venv/bin/python -m linecaster.cli serve --config examples/squiddle_models.json --port 8100
.venv/bin/python examples/squiddle_chain.py IMAGES OUT --backend served --endpoint http://127.0.0.1:8100/v1
```

Add `--files OUT/files` for per-page hOCR, ALTO, PAGE, txt, md and JSON, or `--texts OUT/texts` for one
text per book in each variant.

**A vision-language model per page** (any OpenAI-compatible server, e.g. vLLM):

```bash
.venv/bin/python examples/chat_page.py IMAGES OUT --endpoint http://127.0.0.1:8000/v1
```

**On Hugging Face Jobs.** The recipes start the servers inside each Job and write to a bucket:

```bash
.venv/bin/python recipes/hf-jobs/squiddle_chain.py --run-id my-run --commit <pushed sha> \
    --images hf://datasets/<namespace>/<dataset>@<revision>/images --tasks 4
.venv/bin/python recipes/hf-jobs/chat_page.py --run-id my-vlm-run --commit <pushed sha> \
    --dataset <namespace>/<dataset> --revision <sha> --model lightonai/LightOnOCR-2-1B
```

`squiddle_chain.py --gpus 4 --flavor l4x4` runs one task per GPU on multi-GPU flavors.

## Building blocks

| Kind | Blocks |
|---|---|
| Read | `ImageFolderReader`, `HFImageDatasetReader`, `PageRowReader` (rows of an earlier run) |
| Models | `LayoutStep`, `LinesStep`, `RecognitionStep`, `TablesStep`, `FormulasStep` |
| Vision-language models | `ChatPageStep` (whole page), `ChatRegionStep` (one crop per layout region) |
| Text | `AssignLinesToRegions`, `NormalizeUnicode`, `Typography`, `AssembleDocument`, `ItemTexts` |
| Images | `WorkingImages` (lossless WebP at full resolution), `AttachImage` |
| Checks | `ValidatePages`, `RejectSink` |
| Write | `PageJsonlWriter`, `PageParquetWriter`, `PageFilesWriter`, `ItemTextFilesWriter` |
| Servers in a Job | `ServeModels` (`linecaster serve`), `ServeChatModel` (vLLM) |

## Vision-language models

Each model is a short spec in `src/linecaster/models/`: its prompt, sampling, vLLM flags and how to read
its answer. The specs follow the drivers of the FineBooks BHL OCR leaderboard
([bhl-ocr-eval](https://github.com/finebooks/bhl-ocr-eval)).

| Model | Block |
|---|---|
| `rednote-hilab/dots.mocr` | `ChatPageStep` |
| `allenai/olmOCR-2-7B-1025-FP8` | `ChatPageStep` |
| `lightonai/LightOnOCR-3-4B`, `-0.8B` | `ChatPageStep` |
| `lightonai/LightOnOCR-2-1B` | `ChatPageStep`, `ChatRegionStep` |
| `openbmb/MiniCPM-OCR-1.0` | `ChatRegionStep` |

## Results

Scored with the frozen [bhl-ocr-eval](https://github.com/finebooks/bhl-ocr-eval) harness on all 2,165
pages of the BHL IMPACT ground truth. CER is the character error rate in reading order; lower is better.

| Text | CER | Recall |
|---|---|---|
| BHL's published OCR | 0.0749 | 0.892 |
| Common Pile v0.1 BHL text | 0.0689 | 0.891 |
| squiddle chain on linecaster | 0.0419 | 0.975 |
| MiniCPM-OCR 1.0 on linecaster | 0.0321 | 0.965 |

- The squiddle chain reproduces squiddleocr's output byte for byte, in-process and through the server.
- MiniCPM-OCR through `ChatRegionStep` matches OpenBMB's own SDK on the same pages and the
  leaderboard's row (0.0334).
- On an Nvidia L4 the squiddle chain needs about 0.76 s per page. NOTES.md has the measurements for other
  GPUs.

## Repository layout

```
src/linecaster/        data model, blocks, serve, model specs, Jobs helpers
backends/kraken/       kraken engine (linecaster-kraken)
backends/paddlex/      PaddleX engine (linecaster-paddlex)
envs/kraken-paddlex/   environment with both engines
examples/              local pipelines
recipes/hf-jobs/       Hugging Face Jobs pipelines
specs/                 design of the data model and the serialisers
NOTES.md               measurements and decisions
```

## Licence

Apache-2.0, see [LICENSE](LICENSE).
