The squiddle combination's layout step: PP-DocLayoutV3 (PaddleOCR-VL-1.5's layout model) on ONNX Runtime.
It replaced PP-DocLayout_plus-L as squiddleocr's default on 2026-09-07 because it predicts region polygons and
the reading order itself: PaddleX returns the boxes sorted by the model's order, so the list position is the
reading order (furniture included) and no XY-cut is needed.

Post-processing as PaddleOCR-VL-1.5's pipeline configures it, written out here so the edition does not depend on
code defaults: score threshold 0.3 for every class, PaddleX's layout NMS, and per-class box merging (`large` for
chart, display and inline formula, doc and paragraph title: classes 3, 5, 6, 15 and 17 of the model's 25;
`union` elsewhere). These are what `PaddleLayoutEngine(model_name="PP-DocLayoutV3")` uses by default.

Labels: PaddleX's labels are mapped to DoclingDocument labels as `linecaster_paddlex.layout.LABEL_MAP` does;
`number` (a page number) is not in `labels:` because the engine places it by position: `page_header` when its
center lies in the top `header_zone` (15 %) of the page, else `page_footer`. `seal` stays `seal`, which is not a
DoclingDocument label (the serializers write it as a picture). Regions contained in another by more than
`max_containment` (80 %) of their area are dropped.
