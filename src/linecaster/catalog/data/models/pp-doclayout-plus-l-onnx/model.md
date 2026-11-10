PaddleOCR's PP-DocLayout_plus-L: PP-StructureV3's layout model (RT-DETR-L, 20 classes, boxes without a reading order). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-DocLayout_plus-L_onnx`, an export of `PaddlePaddle/PP-DocLayout_plus-L`; the card does not say from which revision).
License and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on the development machine,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).
