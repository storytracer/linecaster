# deepseek-ocr

*Model · DeepSeek-OCR · MIT*

DeepSeek-OCR ("Contexts Optical Compression", arXiv 2510.18234) is DeepSeek AI's document OCR model built
around visual-token compression. With the `<|grounding|>Convert the document to markdown.` prompt it returns
Markdown with grounding (layout type and box) markers; `Free OCR.` gives plain text. It needs
`trust_remote_code` (custom code) and is supported in upstream vLLM. The card says "multilingual" without a
list and names no base model. Licence: MIT (licence file copied as
`upstream/9f30c71f441d010e5429c532364a86705536c53a/LICENSE`).
The upstream card is in `upstream/9f30c71f441d010e5429c532364a86705536c53a/README.md`.

|  |  |
|---|---|
| Source | [deepseek-ai/DeepSeek-OCR](https://huggingface.co/deepseek-ai/DeepSeek-OCR) |
| Licence | MIT |
| Languages | mul |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `9f30c71f441d010e5429c532364a86705536c53a` | 2026-11-03 |  | 6 | [README.md](../../../src/linecaster/catalog/data/models/deepseek-ocr/upstream/9f30c71f441d010e5429c532364a86705536c53a/README.md) |

## Presets

- [`deepseek-ocr`](../presets/page/deepseek-ocr.md)
