---
schema: linecaster.model/1
id: rt-detr-l-wired-table-cell-det-onnx
version: RT-DETR-L_wired_table_cell_det
source:
  kind: hf
  ref: PaddlePaddle/RT-DETR-L_wired_table_cell_det_onnx
pins:
- revision: b2c0720b5fe6f1c0dd40f8a7993a3f28e04252f8
  pinned: 2026-11-03
  files:
    inference.onnx: sha256:bf5490020512a31f43813d90feadae9526a2c3474ffe807571f2c23594f5958f
  card: upstream/b2c0720b5fe6f1c0dd40f8a7993a3f28e04252f8/README.md
  card_sha256: sha256:35a47ac0d3bd2eb4c7f97b709e6aca50e80f525d5e88ad3ee2d56a3f84784b83
license: Apache-2.0
languages:
- eng
- zho
scripts: []
derived_from:
- ref: PaddlePaddle/RT-DETR-L_wired_table_cell_det
  relation: converted
---

PaddleOCR's RT-DETR-L_wired_table_cell_det: the cell detector for wired (ruled) tables in PaddleX's table pipeline. This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/RT-DETR-L_wired_table_cell_det_onnx`, an export of `PaddlePaddle/RT-DETR-L_wired_table_cell_det`; the card does not say from which revision).
Licence and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).
