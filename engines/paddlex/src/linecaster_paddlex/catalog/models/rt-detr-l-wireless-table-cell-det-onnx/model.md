---
schema: linecaster.model/1
id: rt-detr-l-wireless-table-cell-det-onnx
version: RT-DETR-L_wireless_table_cell_det
source:
  kind: hf
  ref: PaddlePaddle/RT-DETR-L_wireless_table_cell_det_onnx
pins:
- revision: 94c021be206064f0136ef1383fbd4b68b168fa61
  pinned: 2026-11-03
  files:
    inference.onnx: sha256:47515940ec5c37156e09aa9acb20c4e7e22456cad6ce49473661f1762fb46a78
  card: upstream/94c021be206064f0136ef1383fbd4b68b168fa61/README.md
  card_sha256: sha256:66ed2fd7d9b753459831a9683122f2c7deeffa9708aede14c80dfefc0ea91c40
license: Apache-2.0
languages:
- eng
- zho
scripts: []
derived_from:
- ref: PaddlePaddle/RT-DETR-L_wireless_table_cell_det
  relation: converted
---

PaddleOCR's RT-DETR-L_wireless_table_cell_det: the cell detector for wireless (unruled) tables in PaddleX's table pipeline. This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/RT-DETR-L_wireless_table_cell_det_onnx`, an export of `PaddlePaddle/RT-DETR-L_wireless_table_cell_det`; the card does not say from which revision).
Licence and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).
