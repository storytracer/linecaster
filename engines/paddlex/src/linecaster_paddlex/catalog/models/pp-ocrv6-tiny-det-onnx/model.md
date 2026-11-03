---
schema: linecaster.model/1
id: pp-ocrv6-tiny-det-onnx
version: PP-OCRv6_tiny_det
source:
  kind: hf
  ref: PaddlePaddle/PP-OCRv6_tiny_det_onnx
pins:
- revision: 2ba1506c0380b8f0b03dd142459aac66d4421f6c
  pinned: 2026-11-03
  files:
    inference.onnx: sha256:193bab7a04fca699a6c82e6abb5b81bdb28177f0abd4062552b04908dafb19f8
  card: upstream/2ba1506c0380b8f0b03dd142459aac66d4421f6c/README.md
  card_sha256: sha256:f48628931a5dc994ce5c67e32c94d71b4a7e96b8c5c1b00663284999c3c566bc
license: Apache-2.0
languages:
- eng
- zho
scripts: []
params: 0.43M
derived_from:
- ref: PaddlePaddle/PP-OCRv6_tiny_det
  relation: converted
---

PaddleOCR's PP-OCRv6_tiny_det: a DB text-line detector (LCNetV4 backbone, RepLKFPN neck). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-OCRv6_tiny_det_onnx`, an export of `PaddlePaddle/PP-OCRv6_tiny_det`; the card does not say from which revision).
Licence and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. Not compared with PaddleX's own download for this model (the models that were
compared on three pages gave identical outputs, 2026-11-03).
