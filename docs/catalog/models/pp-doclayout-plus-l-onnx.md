# pp-doclayout-plus-l-onnx

*Model · PP-DocLayout_plus-L · Apache-2.0*

PaddleOCR's PP-DocLayout_plus-L: PP-StructureV3's layout model (RT-DETR-L, 20 classes, boxes without a reading order). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-DocLayout_plus-L_onnx`, an export of `PaddlePaddle/PP-DocLayout_plus-L`; the card does not say from which revision).
License and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).

|  |  |
|---|---|
| Source | [PaddlePaddle/PP-DocLayout_plus-L_onnx](https://huggingface.co/PaddlePaddle/PP-DocLayout_plus-L_onnx) |
| License | Apache-2.0 |
| Languages | eng, zho |
| Derived from | converted of PaddlePaddle/PP-DocLayout_plus-L |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `feb74619326f634e0e883218598096a3733ad9f7` | 2026-11-03 |  | 1 | [README.md](../../../src/linecaster/catalog/data/models/pp-doclayout-plus-l-onnx/upstream/feb74619326f634e0e883218598096a3733ad9f7/README.md) |

## Presets

- [`pp-doclayout-plus-l`](../presets/layout/pp-doclayout-plus-l.md)
