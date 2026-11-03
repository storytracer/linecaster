# ovisocr3

*Model · OvisOCR3 · Apache-2.0*

OvisOCR3 is ATH-MaaS's unified 0.8B model for OCR and document understanding, the successor to OvisOCR2. Task
prompts select document parsing (Markdown with LaTeX formulas and HTML tables, structured JSON with box,
category and content, or layout JSON without text), general OCR, key information extraction, figure captioning
and cross-page table reconstruction. It is built on Qwen3.5-0.8B (continued pretraining, mid-training,
on-policy distillation, RL). The card claims no languages. Licence: Apache-2.0 (licence file copied as
`upstream/5f6ce6932efee9ec10c30746db55bd780214b7fd/LICENSE`).
The upstream card is in `upstream/5f6ce6932efee9ec10c30746db55bd780214b7fd/README.md`.

|  |  |
|---|---|
| Source | [ATH-MaaS/OvisOCR3](https://huggingface.co/ATH-MaaS/OvisOCR3) |
| Licence | Apache-2.0 |
| Parameters | 0.8B |
| Derived from | finetuned of Qwen/Qwen3.5-0.8B |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `5f6ce6932efee9ec10c30746db55bd780214b7fd` | 2026-11-03 |  | 4 | [README.md](../../../src/linecaster/catalog/data/models/ovisocr3/upstream/5f6ce6932efee9ec10c30746db55bd780214b7fd/README.md) |

## Presets

- [`ovisocr3`](../presets/page/ovisocr3.md)
