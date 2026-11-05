# pp-ocrv6-medium-det-onnx

*Model · PP-OCRv6_medium_det · Apache-2.0*

PaddleOCR's PP-OCRv6_medium_det: a DB text-line detector (LCNetV4 backbone, RepLKFPN neck). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-OCRv6_medium_det_onnx`, an export of `PaddlePaddle/PP-OCRv6_medium_det`; the card does not say from which revision).
License and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).

|  |  |
|---|---|
| Source | [PaddlePaddle/PP-OCRv6_medium_det_onnx](https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_det_onnx) |
| License | Apache-2.0 |
| Languages | eng, zho |
| Parameters | 15.5M |
| Derived from | converted of PaddlePaddle/PP-OCRv6_medium_det |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `61323801669c338b7891481ec7bac61ce31b576a` | 2026-11-03 |  | 1 | [README.md](../../../src/linecaster/catalog/data/models/pp-ocrv6-medium-det-onnx/upstream/61323801669c338b7891481ec7bac61ce31b576a/README.md) |

## Presets

- [`pp-ocrv6-medium-det`](../presets/lines/pp-ocrv6-medium-det.md)
