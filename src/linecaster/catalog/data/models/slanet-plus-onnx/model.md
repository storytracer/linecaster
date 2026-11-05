PaddleOCR's SLANet_plus: a table structure recogniser (HTML structure tokens and cell boxes). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/SLANet_plus_onnx`, an export of `PaddlePaddle/SLANet_plus`; the card does not say from which revision).
Licence and languages are the card's. The upstream card of the ONNX package is empty but for its licence.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).
