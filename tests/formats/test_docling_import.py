"""A DoclingDocument read as a transcription (a ground truth's import): regions with roles and boxes, lines,
heading levels, tables, the annotator and the source."""
from __future__ import annotations

from linecaster.formats.docling import build_docling, from_docling, to_text
from linecaster.testing import sample_transcription


def test_a_rendered_page_reads_back_with_its_roles_boxes_and_text():
    t = sample_transcription()
    doc = build_docling(t, "p1", 1600, 2400)
    g = from_docling(doc, page_no=1, ground_truth=True, dataset="example.org/gt@0123abc", record="p1")
    assert g.source.kind == "ground_truth" and g.source.dataset == "example.org/gt@0123abc"
    assert g.annotators[0].kind == "human" and g.annotators[0].name == "docling"
    assert [g.role(r.id) for r in g.regions] == ["header", "title", "paragraph", "picture", "footnote"]
    assert g.regions[0].box == [120.0, 80.0, 1360.0, 60.0]
    assert [s for s in g.text.split("\n") if s] == [s for s in to_text(doc, furniture=True).split("\n") if s]


def test_a_file_without_ground_truth_is_converted_and_a_table_renders():
    from linecaster.data.upgrade import upgrade_transcription

    t = upgrade_transcription({"regions": [{"id": "table_0", "label": "table", "polygon": [[0, 0], [10, 0], [10, 10],
                                                                                          [0, 10]],
                                            "bbox": [0, 0, 10, 10], "reading_order": 0,
                                            "extra": {"table": {"num_rows": 1, "num_cols": 2, "cells": [
                                                {"row": 0, "col": 0, "text": "a"}, {"row": 0, "col": 1, "text": "b"}]}}}],
                               "lines": [{"id": "table_0_l0", "region_id": "table_0", "text": "a b", "bbox": [0, 0, 10, 10]}],
                               "steps": [{"step": "layout", "name": "test"}]})
    g = from_docling(build_docling(t, "p", 10, 10))
    assert g.source.kind == "converted" and g.annotators[0].kind == "file"
    assert g.table("table_0").cells[1].text == "b" and g.text == t.text
