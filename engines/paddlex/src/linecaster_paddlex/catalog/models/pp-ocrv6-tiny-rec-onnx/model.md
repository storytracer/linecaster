---
schema: linecaster.model/1
id: pp-ocrv6-tiny-rec-onnx
version: PP-OCRv6_tiny_rec
source:
  kind: hf
  ref: PaddlePaddle/PP-OCRv6_tiny_rec_onnx
pins:
- revision: 2612ab37152ae0a677521bae4e1e3d4fb4cf7c30
  pinned: 2026-11-03
  files:
    inference.onnx: sha256:9ef676d6ed3c88256a2d92c640c44f25b0c40947e111b14b8be8f594091563e6
  card: upstream/2612ab37152ae0a677521bae4e1e3d4fb4cf7c30/README.md
  card_sha256: sha256:e83dd03e515a2d064eaba8ec82248f21dbf6a0813550bafe4c70ee2f6e8fdf2a
license: Apache-2.0
languages:
- eng
- zho
scripts: []
params: 1.1M
derived_from:
- ref: PaddlePaddle/PP-OCRv6_tiny_rec
  relation: converted
---

PaddleOCR's PP-OCRv6_tiny_rec: a CTC text-line recogniser (LCNetV4 backbone, CTC+NRTR heads; CTC decoding in PaddleX). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-OCRv6_tiny_rec_onnx`, an export of `PaddlePaddle/PP-OCRv6_tiny_rec`; the card does not say from which revision).
Licence and languages are the card's. The card names 50 languages in its prose but lists only `en` and `zh` in its metadata, so the document has those two; scripts are left empty (the card names none).

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. Not compared with PaddleX's own download for this model (the models that were
compared on three pages gave identical outputs, 2026-11-03).
