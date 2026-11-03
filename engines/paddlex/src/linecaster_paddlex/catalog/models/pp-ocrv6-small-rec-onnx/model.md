---
schema: linecaster.model/1
id: pp-ocrv6-small-rec-onnx
version: PP-OCRv6_small_rec
source:
  kind: hf
  ref: PaddlePaddle/PP-OCRv6_small_rec_onnx
pins:
- revision: b8f84f0b80c529de40b4fbb3544b84fa7233a513
  pinned: 2026-11-03
  files:
    inference.onnx: sha256:5435fd747c9e0efe15a96d0b378d5bd157e9492ed8fd80edf08f30d02fa24634
  card: upstream/b8f84f0b80c529de40b4fbb3544b84fa7233a513/README.md
  card_sha256: sha256:7d46dbd183ac09bd5a2e6b4577dcb29240751b1c00eb6813eca308d529f86806
license: Apache-2.0
languages:
- eng
- zho
scripts: []
params: 5.2M
derived_from:
- ref: PaddlePaddle/PP-OCRv6_small_rec
  relation: converted
---

PaddleOCR's PP-OCRv6_small_rec: a CTC text-line recogniser (LCNetV4 backbone, CTC+NRTR heads; CTC decoding in PaddleX). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-OCRv6_small_rec_onnx`, an export of `PaddlePaddle/PP-OCRv6_small_rec`; the card does not say from which revision).
Licence and languages are the card's. The card names 50 languages in its prose but lists only `en` and `zh` in its metadata, so the document has those two; scripts are left empty (the card names none).

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).
