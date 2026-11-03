---
schema: linecaster.model/1
id: pp-formulanet-plus-l-safetensors
version: PP-FormulaNet_plus-L
source:
  kind: hf
  ref: PaddlePaddle/PP-FormulaNet_plus-L_safetensors
pins:
- revision: 6cc004a8e91ea3f3819b05317f40b290cbe99c2b
  pinned: 2026-11-03
  files:
    model.safetensors: sha256:582848cf9b7066bb1cf3166ad75a476da492c3661ffa61bb7439f9fd098bde13
  card: upstream/6cc004a8e91ea3f3819b05317f40b290cbe99c2b/README.md
  card_sha256: sha256:4bcf87ecfbbb8e07a01b21415a970c8b53a5283bf6872b657040d3f45c9241f7
license: Apache-2.0
languages: []
scripts: []
derived_from:
- ref: PaddlePaddle/PP-FormulaNet_plus-L
  relation: converted
---

PaddleOCR's PP-FormulaNet_plus-L, a formula recogniser (formula image in, LaTeX out), in the safetensors package PaddleX
downloads for its transformers engine (`PaddlePaddle/PP-FormulaNet_plus-L_safetensors`: Hugging Face transformers on torch; the
official model source has no ONNX package for it). A conversion of `PaddlePaddle/PP-FormulaNet_plus-L`; the card does not say
from which revision, and is empty but for its licence. Formula recognition has no natural language, so
`languages` and `scripts` stay empty.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).
