# pp-doclayoutv3

*Preset · edition 1 · layout · core*

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
centre lies in the top `header_zone` (15 %) of the page, else `page_footer`. `seal` stays `seal`, which is not a
DoclingDocument label (the serialisers write it as a picture). Regions contained in another by more than
`max_containment` (80 %) of their area are dropped.

|  |  |
|---|---|
| Step | layout (reads pages) |
| Engine | [`paddlex.layout.v1`](../../engines/paddlex.layout.v1.md) |
| Model | [PP-DocLayoutV3](../../models/pp-doclayoutv3-onnx.md) |
| Revision | [`46bbdf188bb0a772c08aed74882ce7e51a8f1ea6`](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_onnx/tree/46bbdf188bb0a772c08aed74882ce7e51a8f1ea6) |
| Licence | Apache-2.0 |
| Produces | regions, reading_order |

## Options

| Option | Value |
|---|---|
| model_name | `PP-DocLayoutV3` |
| threshold | `0.3` |
| header_zone | `0.15` |
| nms | `True` |
| merge_mode | `{0: 'union', 1: 'union', 2: 'union', 3: 'large', 4: 'union', 5: 'large', 6: 'large', 7: 'union', 8: 'union', 9: 'union', 10: 'union', 11: 'union', 12: 'union', 13: 'union', 14: 'union', 15: 'large', 16: 'union', 17: 'large', 18: 'union', 19: 'union', 20: 'union', 21: 'union', 22: 'union', 23: 'union', 24: 'union'}` |
| max_containment | `0.8` |

## Provenance

- storytracer/squiddleocr@7c8a052 (the settings its goldens were recorded with: sample-60, tables-7)
