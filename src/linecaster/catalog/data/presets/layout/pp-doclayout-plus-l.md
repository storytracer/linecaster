---
schema: linecaster.preset/1
id: pp-doclayout-plus-l
edition: 1
step: layout
model:
  id: pp-doclayout-plus-l-onnx
  revision: feb74619326f634e0e883218598096a3733ad9f7
engine: paddlex.layout.v1
options:
  model_name: PP-DocLayout_plus-L
  threshold:
    0: 0.3
    1: 0.5
    2: 0.4
    3: 0.5
    4: 0.5
    5: 0.5
    6: 0.5
    7: 0.3
    8: 0.5
    9: 0.5
    10: 0.5
    11: 0.5
    12: 0.5
    13: 0.5
    14: 0.5
    15: 0.45
    16: 0.5
    17: 0.5
    18: 0.5
    19: 0.5
  header_zone: 0.15
  nms: true
  merge_mode: large
  max_containment: 0.8
labels:
  paragraph_title: section_header
  image: picture
  text: text
  abstract: text
  content: text
  figure_title: caption
  formula: formula
  table: table
  reference: reference
  doc_title: title
  footnote: footnote
  header: page_header
  algorithm: code
  footer: page_footer
  seal: seal
  chart: picture
  formula_number: text
  aside_text: text
  reference_content: reference
capabilities:
  unit: page
  produces:
  - regions
  - reading_order
provenance:
  derived_from:
  - 'storytracer/squiddleocr@7c8a052 (the settings its goldens were recorded with: sample-60, tables-7);
    --layout-model PP-DocLayout_plus-L'
  created: 2026-11-03
support: experimental
---

PP-StructureV3's layout model, squiddleocr's earlier default (until 2026-09-07) and its `--layout-model
PP-DocLayout_plus-L`. It gives boxes only, no polygons and no order; the engine orders the regions with
linecaster's XY-cut. Post-processing as PP-StructureV3 configures it, written out: per-class score thresholds
(0.3 for paragraph titles and formulas, 0.4 for text, 0.45 for seals, 0.5 elsewhere), layout NMS, `large` box
merging. On squiddleocr's test scans its regions matched PP-DocLayoutV3's on 5 of 7 pages; the differences were
table boxes and one heading label.

Labels: PaddleX's labels are mapped to DoclingDocument labels as `linecaster_paddlex.layout.LABEL_MAP` does;
`number` (a page number) is not in `labels:` because the engine places it by position: `page_header` when its
centre lies in the top `header_zone` (15 %) of the page, else `page_footer`. `seal` stays `seal`, which is not a
DoclingDocument label (the serialisers write it as a picture). Regions contained in another by more than
`max_containment` (80 %) of their area are dropped.
