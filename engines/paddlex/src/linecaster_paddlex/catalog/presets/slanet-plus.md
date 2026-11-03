---
schema: linecaster.preset/1
id: slanet-plus
edition: 1
step: tables
model:
  id: slanet-plus-onnx
  revision: 7dbe640e127602bf506815e822c09758de73c482
engine:
  kind: paddlex.tables/1
  options:
    crop_pad: 8
    e2e: true
    name: table_recognition_v2/SLANet_plus
    submodel_revisions:
      PP-LCNet_x1_0_table_cls: 605f623b09f67a562bae77e781d5d5266f14905a
      RT-DETR-L_wired_table_cell_det: b2c0720b5fe6f1c0dd40f8a7993a3f28e04252f8
      RT-DETR-L_wireless_table_cell_det: 94c021be206064f0136ef1383fbd4b68b168fa61
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
- The pipeline's other models are pinned through `submodel_revisions`: the wired/wireless classifier
  (`PP-LCNet_x1_0_table_cls`, which picks the branch) and the two cell detectors (loaded by the pipeline, unused
  with `e2e`). Each revision is a pin of its model document.
- Unruled rows come back as one cell per column with every PaddleX table model.
