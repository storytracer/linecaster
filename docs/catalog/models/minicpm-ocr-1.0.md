# minicpm-ocr-1.0

*Model · MiniCPM-OCR 1.0 · Apache-2.0*

MiniCPM-OCR 1.0 is OpenBMB's 1.3B OCR model, the first OCR-specific model of the MiniCPM-V/o family: text,
tables, formulas, charts, seals and key information extraction, with Chinese and English as the primary
languages. Upstream's parsing pipeline pairs it with PP-DocLayoutV3 and assembles Markdown in reading order
(tables as HTML, formulas as LaTeX); field extraction returns JSON. The card says it is trained for OCR on top
of MiniCPM-V 4.6 (SigLIP vision encoder + Qwen3.5 language model). A DSpark speculative-decoding draft head is
published separately (`minicpm-ocr-1.0-dspark`). Licence: Apache-2.0.
The upstream card is in `upstream/a59a4acf215e34c6d73149e9eafdb88ed2086e39/README.md`.

|  |  |
|---|---|
| Source | [openbmb/MiniCPM-OCR-1.0](https://huggingface.co/openbmb/MiniCPM-OCR-1.0) |
| Licence | Apache-2.0 |
| Languages | eng, zho |
| Scripts | Latn, Hani |
| Parameters | 1.3B |
| Derived from | finetuned of openbmb/MiniCPM-V-4.6 |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `a59a4acf215e34c6d73149e9eafdb88ed2086e39` | 2026-11-03 |  | 2 | [README.md](../../../src/linecaster/catalog/data/models/minicpm-ocr-1.0/upstream/a59a4acf215e34c6d73149e9eafdb88ed2086e39/README.md) |

## Presets

- [`minicpm-ocr-1.0`](../presets/recognition/minicpm-ocr-1.0.md)
