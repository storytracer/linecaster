---
schema: linecaster.model/1
id: pp-ocrv6-medium-rec-onnx
version: PP-OCRv6_medium_rec
source:
  kind: hf
  ref: PaddlePaddle/PP-OCRv6_medium_rec_onnx
pins:
- revision: 50c7eacafc52fa7bcf4194e8cd08e46f8558504b
  pinned: 2026-11-03
  files:
    inference.onnx: sha256:9c09abf0957f7968c7586464b7397b84ad2387a0497a351af40e9acc71b673ba
  card: upstream/50c7eacafc52fa7bcf4194e8cd08e46f8558504b/README.md
  card_sha256: sha256:ebce8d28436623ecab4952e24935aed86b3f8ecaf8f8736b92d5544f60fae1e9
license: Apache-2.0
languages:
- eng
- zho
scripts: []
params: 19M
derived_from:
- ref: PaddlePaddle/PP-OCRv6_medium_rec
  relation: converted
---

PaddleOCR's PP-OCRv6_medium_rec: a CTC text-line recogniser (LCNetV4 backbone, CTC+NRTR heads; CTC decoding in PaddleX). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-OCRv6_medium_rec_onnx`, an export of `PaddlePaddle/PP-OCRv6_medium_rec`; the card does not say from which revision).
Licence and languages are the card's. The card names 50 languages in its prose but lists only `en` and `zh` in its metadata, so the document has those two; scripts are left empty (the card names none).

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. Not compared with PaddleX's own download for this model (the models that were
compared on three pages gave identical outputs, 2026-11-03).
