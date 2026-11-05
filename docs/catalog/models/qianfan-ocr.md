# qianfan-ocr

*Model · Qianfan-OCR · Apache-2.0*

Qianfan-OCR is the Baidu Qianfan team's 4B end-to-end document model (arXiv 2603.13398): direct
image-to-Markdown parsing plus prompt-driven tasks (layout analysis, table extraction, key information
extraction to JSON, document questions), with an optional "Layout-as-Thought" thinking phase that first emits
boxes, element types and reading order. It uses the Qianfan-VL architecture: a Qianfan-ViT encoder, a Qwen3-4B
language model and an MLP adapter; the card names no base checkpoint. It claims 192 languages without a list.
Licence: Apache-2.0 (some bundled third-party source files MIT; licence file copied as
`upstream/623bf5d20d446abdb36606aa4547cd0c18886fe5/LICENSE`).
The upstream card is in `upstream/623bf5d20d446abdb36606aa4547cd0c18886fe5/README.md`.

|  |  |
|---|---|
| Source | [baidu/Qianfan-OCR](https://huggingface.co/baidu/Qianfan-OCR) |
| Licence | Apache-2.0 |
| Languages | mul |
| Parameters | 4B |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `623bf5d20d446abdb36606aa4547cd0c18886fe5` | 2026-11-03 |  | 6 | [README.md](../../../src/linecaster/catalog/data/models/qianfan-ocr/upstream/623bf5d20d446abdb36606aa4547cd0c18886fe5/README.md) |

## Presets

- [`qianfan-ocr`](../presets/recognition/qianfan-ocr.md)
