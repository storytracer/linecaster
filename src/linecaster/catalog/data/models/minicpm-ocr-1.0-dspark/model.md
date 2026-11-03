---
schema: linecaster.model/1
id: minicpm-ocr-1.0-dspark
version: MiniCPM-OCR 1.0 DSpark
source:
  kind: hf
  ref: openbmb/MiniCPM-OCR-1.0-DSpark
pins:
- revision: 31e3feaf80e0061cd6aa73db23480d2d691d6452
  pinned: 2026-11-03
  files:
    model.safetensors: sha256:3e6332e05e2539898a0691db381e3a85877728a754561f9e3d13e597e44c672b
  card: upstream/31e3feaf80e0061cd6aa73db23480d2d691d6452/README.md
  card_sha256: sha256:2da4db4f37791a1b3ceb7c4a1ab47477bea7d64c0f41649286a32ecd863f4993
license: Apache-2.0
languages:
- eng
- zho
scripts:
- Latn
- Hani
params: 297M
derived_from:
- ref: openbmb/MiniCPM-OCR-1.0
  relation: finetuned
---

MiniCPM-OCR 1.0 DSpark is OpenBMB's DSpark speculative-decoding draft head for MiniCPM-OCR 1.0: a small
5-layer draft model (296,837,889 parameters, BF16) that proposes tokens the main model verifies. It is not an
OCR model on its own and must be paired with the matching `minicpm-ocr-1.0` checkpoint (vLLM usage in the
card). Its `d2t` tensor is delta-encoded and must be converted to absolute ids before use. The card front
matter gives `openbmb/MiniCPM-OCR-1.0` as base model (relation `finetune`). Licence: Apache-2.0.
The upstream card is in `upstream/31e3feaf80e0061cd6aa73db23480d2d691d6452/README.md`.
