---
schema: linecaster.model/1
id: pp-ocrv6-medium-det-onnx
version: PP-OCRv6_medium_det
source:
  kind: hf
  ref: PaddlePaddle/PP-OCRv6_medium_det_onnx
pins:
- revision: 61323801669c338b7891481ec7bac61ce31b576a
  pinned: 2026-11-03
  files:
    inference.onnx: sha256:eb13b44b25bb36f89528b68720af8a61d9cf381176107f465db1757b65d086e1
  card: upstream/61323801669c338b7891481ec7bac61ce31b576a/README.md
  card_sha256: sha256:3046e3aab0194a2291bb3941c93b980c2b3a938a24a5be88354968f6d6187ac8
license: Apache-2.0
languages:
- eng
- zho
scripts: []
params: 15.5M
derived_from:
- ref: PaddlePaddle/PP-OCRv6_medium_det
  relation: converted
---

PaddleOCR's PP-OCRv6_medium_det: a DB text-line detector (LCNetV4 backbone, RepLKFPN neck). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-OCRv6_medium_det_onnx`, an export of `PaddlePaddle/PP-OCRv6_medium_det`; the card does not say from which revision).
Licence and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).
