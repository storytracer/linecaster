# pp-ocrv6-tiny-det-onnx

*Model · PP-OCRv6_tiny_det · Apache-2.0*

PaddleOCR's PP-OCRv6_tiny_det: a DB text-line detector (LCNetV4 backbone, RepLKFPN neck). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-OCRv6_tiny_det_onnx`, an export of `PaddlePaddle/PP-OCRv6_tiny_det`; the card does not say from which revision).
Licence and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. Not compared with PaddleX's own download for this model (the models that were
compared on three pages gave identical outputs, 2026-11-03).

|  |  |
|---|---|
| Source | [PaddlePaddle/PP-OCRv6_tiny_det_onnx](https://huggingface.co/PaddlePaddle/PP-OCRv6_tiny_det_onnx) |
| Licence | Apache-2.0 |
| Languages | eng, zho |
| Parameters | 0.43M |
| Derived from | converted of PaddlePaddle/PP-OCRv6_tiny_det |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `2ba1506c0380b8f0b03dd142459aac66d4421f6c` | 2026-11-03 |  | 1 | [README.md](../../../src/linecaster/catalog/data/models/pp-ocrv6-tiny-det-onnx/upstream/2ba1506c0380b8f0b03dd142459aac66d4421f6c/README.md) |

## Presets

- [`pp-ocrv6-tiny-det`](../presets/lines/pp-ocrv6-tiny-det.md)
