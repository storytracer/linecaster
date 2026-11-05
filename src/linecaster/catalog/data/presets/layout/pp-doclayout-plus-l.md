PP-StructureV3's layout model, squiddleocr's earlier default (until 2026-09-07) and its `--layout-model
PP-DocLayout_plus-L`. It gives boxes only, no polygons and no order; the engine orders the regions with
linecaster's XY-cut. Post-processing as PP-StructureV3 configures it, written out: per-class score thresholds
(0.3 for paragraph titles and formulas, 0.4 for text, 0.45 for seals, 0.5 elsewhere), layout NMS, `large` box
merging. On squiddleocr's test scans its regions matched PP-DocLayoutV3's on 5 of 7 pages; the differences were
table boxes and one heading label.

Labels: PaddleX's labels are mapped to DoclingDocument labels as `linecaster_paddlex.layout.LABEL_MAP` does;
`number` (a page number) is not in `labels:` because the engine places it by position: `page_header` when its
center lies in the top `header_zone` (15 %) of the page, else `page_footer`. `seal` stays `seal`, which is not a
DoclingDocument label (the serializers write it as a picture). Regions contained in another by more than
`max_containment` (80 %) of their area are dropped.
