PaddleOCR's PP-FormulaNet_plus-L, a formula recognizer (formula image in, LaTeX out), in the safetensors package PaddleX
downloads for its transformers engine (`PaddlePaddle/PP-FormulaNet_plus-L_safetensors`: Hugging Face transformers on torch; the
official model source has no ONNX package for it). A conversion of `PaddlePaddle/PP-FormulaNet_plus-L`; the card does not say
from which revision, and is empty but for its license. Formula recognition has no natural language, so
`languages` and `scripts` stay empty.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).
