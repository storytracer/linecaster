---
schema: linecaster.preset/1
id: slanet-plus
edition: 2
step: tables
model:
  id: slanet-plus-onnx
  revision: 7dbe640e127602bf506815e822c09758de73c482
submodels:
  PP-LCNet_x1_0_table_cls:
    id: pp-lcnet-x1-0-table-cls-onnx
    revision: 605f623b09f67a562bae77e781d5d5266f14905a
  RT-DETR-L_wired_table_cell_det:
    id: rt-detr-l-wired-table-cell-det-onnx
    revision: b2c0720b5fe6f1c0dd40f8a7993a3f28e04252f8
  RT-DETR-L_wireless_table_cell_det:
    id: rt-detr-l-wireless-table-cell-det-onnx
    revision: 94c021be206064f0136ef1383fbd4b68b168fa61
engine: paddlex.tables.v1
options:
  crop_pad: 8
  e2e: true
  name: table_recognition_v2/SLANet_plus
capabilities:
  unit: region
  produces:
  - tables
  - html
provenance:
  derived_from:
  - 'storytracer/squiddleocr@7c8a052 (the settings its goldens were recorded with: sample-60, tables-7)'
  created: 2026-11-03
support: core
---

PaddleX's `table_recognition_v2` pipeline on every `table` region, fed with the page's own lines and their
recognised text instead of its own OCR (`use_ocr_model=False` with an external OCR result); the cells come back
with our text in PaddleX's HTML. The squiddle combination's table step.

- SLANet_plus end to end for both table classes (`e2e`: structure and cell boxes from SLANet_plus's own
  prediction, the RT-DETR cell detectors unused). Chosen 2026-09-07 from four variants on five BHL tables:
  PP-StructureV3's own choice (SLANeXt_wired + cell detector for what the classifier calls wired) merged body rows
  on old ruled tables; SLANet_plus end to end kept every body row apart and filled the most cells.
- `crop_pad` 8: with the layout box exactly, the models can flip to a worse cell set (25 cells and 44 words on one
  table against 17 cells and 121 words padded); from 8 px the result is stable.
- The pipeline's other models are its `submodels`, by PaddleX name: the wired/wireless classifier
  (`PP-LCNet_x1_0_table_cls`, which picks the branch) and the two cell detectors (loaded by the pipeline, unused
  with `e2e`), each a pin of its model document, so their files are part of the edition's hash.

Edition 2 (2026-11-03): the same models at the same revisions, moved from the option `submodel_revisions` (edition
1) to `submodels`, so their file hashes count too. Edition 1 was dropped from the lock when the catalogues were
merged into one (2026-11-04), before any run recorded it.
- Unruled rows come back as one cell per column with every PaddleX table model.
