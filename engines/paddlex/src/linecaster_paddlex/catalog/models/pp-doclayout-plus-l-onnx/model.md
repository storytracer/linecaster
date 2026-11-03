---
schema: linecaster.model/1
id: pp-doclayout-plus-l-onnx
version: PP-DocLayout_plus-L
source:
  kind: hf
  ref: PaddlePaddle/PP-DocLayout_plus-L_onnx
pins:
- revision: feb74619326f634e0e883218598096a3733ad9f7
  pinned: 2026-11-03
  files:
    inference.onnx: sha256:77afb2caa74dd13240d087d2eced91d7fcd2caebd16006a0a66162fc8707ff0e
  card: upstream/feb74619326f634e0e883218598096a3733ad9f7/README.md
  card_sha256: sha256:91328b1af981a8992c803b6d4be88185b4407e09450650ec5f5a4941a8b99d99
license: Apache-2.0
languages:
- eng
- zho
scripts: []
derived_from:
- ref: PaddlePaddle/PP-DocLayout_plus-L
  relation: converted
---

PaddleOCR's PP-DocLayout_plus-L: PP-StructureV3's layout model (RT-DETR-L, 20 classes, boxes without a reading order). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-DocLayout_plus-L_onnx`, an export of `PaddlePaddle/PP-DocLayout_plus-L`; the card does not say from which revision).
Licence and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).
