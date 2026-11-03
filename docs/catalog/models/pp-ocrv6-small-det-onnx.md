# pp-ocrv6-small-det-onnx

*Model · PP-OCRv6_small_det · Apache-2.0*

PaddleOCR's PP-OCRv6_small_det: a DB text-line detector (LCNetV4 backbone, RepLKFPN neck). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-OCRv6_small_det_onnx`, an export of `PaddlePaddle/PP-OCRv6_small_det`; the card does not say from which revision).
Licence and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. Not compared with PaddleX's own download for this model (the models that were
compared on three pages gave identical outputs, 2026-11-03).

|  |  |
|---|---|
| Source | [PaddlePaddle/PP-OCRv6_small_det_onnx](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_det_onnx) |
| Licence | Apache-2.0 |
| Languages | eng, zho |
| Parameters | 2.48M |
| Derived from | converted of PaddlePaddle/PP-OCRv6_small_det |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `28fe5895c24fd108c19eb3e8479f4ab385fbfc62` | 2026-11-03 |  | 1 | [README.md](../../../src/linecaster/catalog/data/models/pp-ocrv6-small-det-onnx/upstream/28fe5895c24fd108c19eb3e8479f4ab385fbfc62/README.md) |

## Presets

- [`pp-ocrv6-small-det`](../presets/lines/pp-ocrv6-small-det.md)
