PaddleX's `table_recognition_v2` pipeline on every `table` region, fed with the page's own lines and their
recognized text instead of its own OCR (`use_ocr_model=False` with an external OCR result); the cells come back
with our text in PaddleX's HTML. The squiddle combination's table step.

- SLANet_plus end to end for both table classes (`e2e`: structure and cell boxes from SLANet_plus's own
  prediction, the RT-DETR cell detectors unused), linecaster's choice where PP-StructureV3 uses SLANeXt_wired with
  a cell detector for what the classifier calls wired.
- `crop_pad` 8: the table region's crop is grown by 8 px on every side (linecaster's choice).
- The pipeline's other models are its `submodels`, by PaddleX name: the wired/wireless classifier
  (`PP-LCNet_x1_0_table_cls`, which picks the branch) and the two cell detectors (loaded by the pipeline, unused
  with `e2e`), each a pin of its model entry, so their files are part of the edition's hash.

Edition 2 (2026-11-03): the same models at the same revisions, moved from the option `submodel_revisions` (edition
1) to `submodels`, so their file hashes count too. Edition 1 was dropped from the lock when the catalogs were
merged into one (2026-11-04), before any run recorded it.
- Unruled rows come back as one cell per column with every PaddleX table model.
