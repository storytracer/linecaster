# ovisocr2

*Model · OvisOCR2 · Apache-2.0*

OvisOCR2 is a compact 0.8B end-to-end page parser published by ATH-MaaS (arXiv 2607.13639): given a page image
it writes one Markdown document in natural reading order, covering text, formulas, tables and visual regions
(as `<img>` tags carrying the region's box). It is post-trained from Qwen3.5-0.8B (SFT, RL and on-policy
distillation). The card claims no languages. Licence: Apache-2.0 (licence file copied as
`upstream/65c619d374b55d4152e85150fc1b003700bc1f0c/LICENSE`).
The upstream card is in `upstream/65c619d374b55d4152e85150fc1b003700bc1f0c/README.md`.

|  |  |
|---|---|
| Source | [ATH-MaaS/OvisOCR2](https://huggingface.co/ATH-MaaS/OvisOCR2) |
| Licence | Apache-2.0 |
| Parameters | 0.8B |
| Derived from | finetuned of Qwen/Qwen3.5-0.8B |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `65c619d374b55d4152e85150fc1b003700bc1f0c` | 2026-11-03 |  | 5 | [README.md](../../../src/linecaster/catalog/data/models/ovisocr2/upstream/65c619d374b55d4152e85150fc1b003700bc1f0c/README.md) |

## Presets

- [`ovisocr2`](../presets/page/ovisocr2.md)
