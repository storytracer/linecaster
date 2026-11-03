---
schema: linecaster.model/1
id: pp-ocrv6-small-det-onnx
version: PP-OCRv6_small_det
source:
  kind: hf
  ref: PaddlePaddle/PP-OCRv6_small_det_onnx
pins:
- revision: 28fe5895c24fd108c19eb3e8479f4ab385fbfc62
  pinned: 2026-11-03
  files:
    inference.onnx: sha256:d73e0058b7a8086bbd57f3d10b8bcd4ff95363f67e06e2762b5e814fe9c9410e
  card: upstream/28fe5895c24fd108c19eb3e8479f4ab385fbfc62/README.md
  card_sha256: sha256:e9403667f0f92055d8ce9e73a2beb1002fc489d9342697db74039eb7178bb5fb
license: Apache-2.0
languages:
- eng
- zho
scripts: []
params: 2.48M
derived_from:
- ref: PaddlePaddle/PP-OCRv6_small_det
  relation: converted
---

PaddleOCR's PP-OCRv6_small_det: a DB text-line detector (LCNetV4 backbone, RepLKFPN neck). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-OCRv6_small_det_onnx`, an export of `PaddlePaddle/PP-OCRv6_small_det`; the card does not say from which revision).
Licence and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. Not compared with PaddleX's own download for this model (the models that were
compared on three pages gave identical outputs, 2026-11-03).
