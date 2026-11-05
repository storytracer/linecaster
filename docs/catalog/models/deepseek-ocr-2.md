# deepseek-ocr-2

*Model · DeepSeek-OCR 2 · Apache-2.0*

DeepSeek-OCR 2 ("Visual Causal Flow", arXiv 2601.20552) is DeepSeek AI's successor to DeepSeek-OCR, with a new
visual encoding and dynamic resolution (up to six 768x768 crops plus one 1024x1024 global view). The prompts
are the same: `<|grounding|>Convert the document to markdown.` for Markdown with grounding markers, `Free
OCR.` for text without layout. It needs `trust_remote_code` (custom code). The card says "multilingual"
without a list and names no base model. License: Apache-2.0 (unlike DeepSeek-OCR, which is MIT; license file
copied as `upstream/aaa02f3811945a91062062994c5c4a3f4c0af2b0/LICENSE.txt`).
The upstream card is in `upstream/aaa02f3811945a91062062994c5c4a3f4c0af2b0/README.md`.

|  |  |
|---|---|
| Source | [deepseek-ai/DeepSeek-OCR-2](https://huggingface.co/deepseek-ai/DeepSeek-OCR-2) |
| License | Apache-2.0 |
| Languages | mul |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `aaa02f3811945a91062062994c5c4a3f4c0af2b0` | 2026-11-03 |  | 2 | [README.md](../../../src/linecaster/catalog/data/models/deepseek-ocr-2/upstream/aaa02f3811945a91062062994c5c4a3f4c0af2b0/README.md) |

## Presets

- [`deepseek-ocr-2`](../presets/recognition/deepseek-ocr-2.md)
