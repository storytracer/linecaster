# pp-ocrv6-small-rec-onnx

*Model · PP-OCRv6_small_rec · Apache-2.0*

PaddleOCR's PP-OCRv6_small_rec: a CTC text-line recogniser (LCNetV4 backbone, CTC+NRTR heads; CTC decoding in PaddleX). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-OCRv6_small_rec_onnx`, an export of `PaddlePaddle/PP-OCRv6_small_rec`; the card does not say from which revision).
Licence and languages are the card's. The card names 50 languages in its prose but lists only `en` and `zh` in its metadata, so the document has those two; scripts are left empty (the card names none).

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).

|  |  |
|---|---|
| Source | [PaddlePaddle/PP-OCRv6_small_rec_onnx](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_rec_onnx) |
| Licence | Apache-2.0 |
| Languages | eng, zho |
| Parameters | 5.2M |
| Derived from | converted of PaddlePaddle/PP-OCRv6_small_rec |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `b8f84f0b80c529de40b4fbb3544b84fa7233a513` | 2026-11-03 |  | 1 | [README.md](../../../src/linecaster/catalog/data/models/pp-ocrv6-small-rec-onnx/upstream/b8f84f0b80c529de40b4fbb3544b84fa7233a513/README.md) |

## Presets

- [`paddlex-ppocrv6-small`](../presets/recognition/paddlex-ppocrv6-small.md)
