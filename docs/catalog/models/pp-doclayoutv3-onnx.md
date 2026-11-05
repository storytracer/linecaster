# pp-doclayoutv3-onnx

*Model · PP-DocLayoutV3 · Apache-2.0*

PaddleOCR's PP-DocLayoutV3, the layout model of PaddleOCR-VL-1.5, in the ONNX package PaddleX downloads for its
ONNX Runtime engine (`PaddlePaddle/PP-DocLayoutV3_onnx`, an export of `PaddlePaddle/PP-DocLayoutV3`; the card
does not say from which revision). 25 classes (`inference.yml`), region polygons and a learned reading order:
PaddleX returns the boxes sorted by the model's order. License and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).

|  |  |
|---|---|
| Source | [PaddlePaddle/PP-DocLayoutV3_onnx](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_onnx) |
| License | Apache-2.0 |
| Languages | eng, zho, mul |
| Derived from | converted of PaddlePaddle/PP-DocLayoutV3 |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `46bbdf188bb0a772c08aed74882ce7e51a8f1ea6` | 2026-11-03 |  | 1 | [README.md](../../../src/linecaster/catalog/data/models/pp-doclayoutv3-onnx/upstream/46bbdf188bb0a772c08aed74882ce7e51a8f1ea6/README.md) |

## Presets

- [`pp-doclayoutv3`](../presets/layout/pp-doclayoutv3.md)
