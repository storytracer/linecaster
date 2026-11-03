---
schema: linecaster.model/1
id: pp-formulanet-l-safetensors
version: PP-FormulaNet-L
source:
  kind: hf
  ref: PaddlePaddle/PP-FormulaNet-L_safetensors
pins:
- revision: 69869f2891cc61347d230ef234bcc8b8d297c43a
  pinned: 2026-11-03
  files:
    model.safetensors: sha256:8e923c2c2502c8fb9b7bb13cff2498c2dbdbb63d2d98b9e1623674299e716e8f
  card: upstream/69869f2891cc61347d230ef234bcc8b8d297c43a/README.md
  card_sha256: sha256:4bcf87ecfbbb8e07a01b21415a970c8b53a5283bf6872b657040d3f45c9241f7
license: Apache-2.0
languages: []
scripts: []
derived_from:
- ref: PaddlePaddle/PP-FormulaNet-L
  relation: converted
---

PaddleOCR's PP-FormulaNet-L, a formula recogniser (formula image in, LaTeX out), in the safetensors package PaddleX
downloads for its transformers engine (`PaddlePaddle/PP-FormulaNet-L_safetensors`: Hugging Face transformers on torch; the
official model source has no ONNX package for it). A conversion of `PaddlePaddle/PP-FormulaNet-L`; the card does not say
from which revision, and is empty but for its licence. Formula recognition has no natural language, so
`languages` and `scripts` stay empty.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. Not compared with PaddleX's own download for this model (the models that were
compared on three pages gave identical outputs, 2026-11-03).
