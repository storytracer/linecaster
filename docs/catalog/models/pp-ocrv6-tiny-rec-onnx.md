# pp-ocrv6-tiny-rec-onnx

*Model · PP-OCRv6_tiny_rec · Apache-2.0*

PaddleOCR's PP-OCRv6_tiny_rec: a CTC text-line recogniser (LCNetV4 backbone, CTC+NRTR heads; CTC decoding in PaddleX). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-OCRv6_tiny_rec_onnx`, an export of `PaddlePaddle/PP-OCRv6_tiny_rec`; the card does not say from which revision).
Licence and languages are the card's. The card names 50 languages in its prose but lists only `en` and `zh` in its metadata, so the document has those two; scripts are left empty (the card names none).

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. Not compared with PaddleX's own download for this model (the models that were
compared on three pages gave identical outputs, 2026-11-03).

|  |  |
|---|---|
| Source | [PaddlePaddle/PP-OCRv6_tiny_rec_onnx](https://huggingface.co/PaddlePaddle/PP-OCRv6_tiny_rec_onnx) |
| Licence | Apache-2.0 |
| Languages | eng, zho |
| Parameters | 1.1M |
| Derived from | converted of PaddlePaddle/PP-OCRv6_tiny_rec |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `2612ab37152ae0a677521bae4e1e3d4fb4cf7c30` | 2026-11-03 |  | 1 | [README.md](../../../src/linecaster/catalog/data/models/pp-ocrv6-tiny-rec-onnx/upstream/2612ab37152ae0a677521bae4e1e3d4fb4cf7c30/README.md) |

## Presets

- [`paddlex-ppocrv6-tiny`](../presets/recognition/paddlex-ppocrv6-tiny.md)
