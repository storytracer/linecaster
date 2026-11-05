# pp-ocrv6-medium-rec-onnx

*Model · PP-OCRv6_medium_rec · Apache-2.0*

PaddleOCR's PP-OCRv6_medium_rec: a CTC text-line recognizer (LCNetV4 backbone, CTC+NRTR heads; CTC decoding in PaddleX). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-OCRv6_medium_rec_onnx`, an export of `PaddlePaddle/PP-OCRv6_medium_rec`; the card does not say from which revision).
License and languages are the card's. The card names 50 languages in its prose but lists only `en` and `zh` in its metadata, so the document has those two; scripts are left empty (the card names none).

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. Not compared with PaddleX's own download for this model (the models that were
compared on three pages gave identical outputs, 2026-11-03).

|  |  |
|---|---|
| Source | [PaddlePaddle/PP-OCRv6_medium_rec_onnx](https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_rec_onnx) |
| License | Apache-2.0 |
| Languages | eng, zho |
| Parameters | 19M |
| Derived from | converted of PaddlePaddle/PP-OCRv6_medium_rec |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `50c7eacafc52fa7bcf4194e8cd08e46f8558504b` | 2026-11-03 |  | 1 | [README.md](../../../src/linecaster/catalog/data/models/pp-ocrv6-medium-rec-onnx/upstream/50c7eacafc52fa7bcf4194e8cd08e46f8558504b/README.md) |

## Presets

- [`paddlex-ppocrv6-medium`](../presets/recognition/paddlex-ppocrv6-medium.md)
