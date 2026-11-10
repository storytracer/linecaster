PaddleOCR's PP-OCRv6_small_det: a DB text-line detector (LCNetV4 backbone, RepLKFPN neck). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-OCRv6_small_det_onnx`, an export of `PaddlePaddle/PP-OCRv6_small_det`; the card does not say from which revision).
License and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on the development machine,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`.
