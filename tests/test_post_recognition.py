"""Retyper and page composition (the post-recognition CPU blocks ported from squiddleocr)."""
from __future__ import annotations

import pytest

from linecaster.blocks.base import new_page_document, page_of, set_page
from linecaster.blocks.document import ComposePage, PageExportsWriter, Typography
from linecaster.document import build_docling, load_docling, to_markdown, to_text
from linecaster.page import Page
from linecaster.retyper import retype
from linecaster.transcription.model import Line, Region, Transcription


def box(x, y, w, h):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def region(rid, label, x, y, w, h, order, raw=None, **kw):
    return Region(id=rid, label=label, raw_label=raw or label, polygon=box(x, y, w, h), bbox=[x, y, w, h],
                  score=0.9, reading_order=order, **kw)


def line(rid, k, x, y, w, h, text, row=None, conf=0.99):
    return Line(id=f"{rid}_l{k}", region_id=rid, row=k if row is None else row, polygon=box(x, y, w, h),
                bbox=[x, y, w, h], text=text, confidence=conf)


def body_region(rid, order, y0, n=6, h=20, x=100, prefix="body"):
    r = region(rid, "text", x, y0, 800, n * (h + 10), order)
    return r, [line(rid, k, x, y0 + k * (h + 10), 800, h, f"{prefix} {k}") for k in range(n)]


def page_with(regions, lines):
    return Transcription(regions=regions, lines=lines)


# ------------------------------------------------------------------ retyper
def test_heading_levels_and_demotion():
    b, bl = body_region("text_1", 1, 300)
    big = region("doc_title_0", "title", 100, 100, 800, 60, 0)
    sub = region("section_header_2", "section_header", 100, 600, 800, 22, 2)
    mid = region("section_header_3", "section_header", 100, 700, 800, 36, 3)
    t = page_with([big, b, sub, mid], [line("doc_title_0", 0, 100, 100, 800, 60, "TITLE"), *bl,
                                         line("section_header_2", 0, 100, 600, 800, 22, "kicker"),
                                         line("section_header_3", 0, 100, 700, 800, 36, "Chapter")])
    stats = retype(t)
    assert stats.body_size == 20
    assert big.heading_level == 1                      # 3.0x
    assert sub.label == "text" and sub.heading_level is None    # 1.1x: demoted
    assert mid.label == "section_header" and mid.heading_level == 2   # 1.8x
    assert (stats.levelled, stats.demoted) == (2, 1)
    assert t.model[-1].step == "typography" and t.model[-1].measurements["demoted"] == 1


def test_headline_split_off_a_body_region():
    rid = "text_0"
    r = region(rid, "text", 100, 100, 800, 400, 0)
    lines = [line(rid, 0, 100, 100, 800, 50, "HEADLINE"), line(rid, 1, 100, 170, 800, 20, "body a"),
             line(rid, 2, 100, 200, 800, 20, "body b"), line(rid, 3, 100, 230, 800, 20, "body c")]
    other, ol = body_region("text_1", 1, 600)
    t = page_with([r, other], lines + ol)
    stats = retype(t)
    assert stats.split == 1
    ids = [x.id for x in t.regions]
    assert ids == ["text_0_head", "text_0", "text_1"]
    head = t.regions[0]
    assert head.label == "section_header" and head.raw_label == "text/split" and head.heading_level == 1   # 50 / 20 = 2.5
    assert head.bbox == [100.0, 100.0, 800.0, 50.0]
    assert r.bbox == [100.0, 170.0, 800.0, 80.0]               # shrunk to its remaining lines
    assert [x.reading_order for x in t.regions] == [0, 1, 2]
    moved = [ln for ln in t.lines if ln.region_id == "text_0_head"]
    assert [ln.id for ln in moved] == ["text_0_l0"]              # line ids stay
    assert [ln.text for ln in sorted(t.lines, key=lambda l: l.reading_order)][:2] == ["HEADLINE", "body a"]


def test_drop_capital_glued_to_its_paragraph():
    b, bl = body_region("text_1", 1, 300)
    bl[0].text = "ARLY in the morning"
    drop = region("drop_0", "text", 40, 290, 55, 60, 0, raw="drop-capital")
    t = page_with([drop, b], [line("drop_0", 0, 40, 290, 55, 60, "E"), *bl])
    stats = retype(t)
    assert stats.drop_capitals == 1
    assert [x.id for x in t.regions] == ["text_1"] and t.regions[0].reading_order == 0
    assert bl[0].text == "EARLY in the morning" and bl[0].extra["drop_capital"] == "E"
    assert all(ln.region_id != "drop_0" for ln in t.lines)
    assert t.extra["retyper_dropped"][0]["region_id"] == "drop_0"


@pytest.mark.parametrize("conf, kept", [(0.98, True), (0.74, False)])
def test_uncertain_page_numbers_dropped(conf, kept):
    b, bl = body_region("text_1", 1, 300)
    num = region("number_0", "page_header", 450, 40, 40, 20, 0, raw="number")
    head = region("header_2", "page_header", 100, 40, 300, 20, 2, raw="header")   # a running head: never dropped
    t = page_with([num, b, head], [line("number_0", 0, 450, 40, 40, 20, "12", conf=conf), *bl,
                                    line("header_2", 0, 100, 40, 300, 20, "THE BIRDS", conf=0.1)])
    stats = retype(t)
    assert ("number_0" in [x.id for x in t.regions]) is kept
    assert stats.numbers_dropped == (0 if kept else 1)
    assert "header_2" in [x.id for x in t.regions]
    if not kept:
        d = t.extra["retyper_dropped"][0]
        assert d["reason"] == "uncertain page number" and d["text"] == "12" and d["confidence"] == pytest.approx(0.74)
        assert [x.reading_order for x in sorted(t.regions, key=lambda r: r.reading_order)] == [0, 1]


def test_page_number_confidence_is_character_weighted():
    num = region("number_0", "page_footer", 450, 900, 80, 20, 0, raw="number")
    t = page_with([num], [line("number_0", 0, 450, 900, 30, 20, "1", row=0, conf=0.2),
                          line("number_0", 1, 490, 900, 40, 20, "234", row=0, conf=0.95)])
    retype(t)                       # (0.2*1 + 0.95*3) / 4 = 0.7625 >= 0.75: kept
    assert [x.id for x in t.regions] == ["number_0"]


# ------------------------------------------------------------- document
def page_to_compose():
    b, bl = body_region("text_1", 1, 300)
    t = page_with([
        region("doc_title_0", "title", 100, 100, 800, 60, 0),
        b,
        region("number_2", "page_footer", 450, 900, 40, 20, 2, raw="number"),
        region("table_3", "table", 100, 600, 800, 200, 3,
               extra={"table": {"num_rows": 2, "num_cols": 2, "html": None, "cells": [
                   {"text": "a", "row": 0, "col": 0, "row_span": 1, "col_span": 1, "bbox": [100, 600, 400, 100], "header": True},
                   {"text": "b", "row": 0, "col": 1, "row_span": 1, "col_span": 1, "bbox": None, "header": True},
                   {"text": "c", "row": 1, "col": 0, "row_span": 1, "col_span": 1, "bbox": None, "header": False},
                   {"text": "d", "row": 1, "col": 1, "row_span": 1, "col_span": 1, "bbox": None, "header": False}]}}),
        region("image_4", "picture", 100, 820, 300, 60, 4),
        region("text_5", "text", 100, 890, 300, 5, 5),          # no lines: no item
        region("section_header_6", "section_header", 100, 850, 800, 40, None, heading_level=2),
    ], [line("doc_title_0", 0, 100, 100, 800, 60, "THE TITLE"), *bl,
        line("number_2", 0, 450, 900, 40, 20, "12"),
        line("image_4", 0, 100, 820, 140, 20, "Fig. 1", row=0), line("image_4", 1, 250, 820, 140, 20, "left", row=0),
        line("section_header_6", 0, 100, 850, 800, 40, "LAST")])
    return t


def test_build_docling_items_layers_and_order():
    from docling_core.types.doc import ContentLayer, DocItemLabel

    doc = build_docling(page_to_compose(), name="p1", width=1000, height=1000)
    labels = [(it.label, getattr(it, "text", None)) for it, _ in doc.iterate_items(included_content_layers={
        ContentLayer.BODY, ContentLayer.FURNITURE})]
    assert labels[0] == (DocItemLabel.TITLE, "THE TITLE")
    assert labels[1] == (DocItemLabel.TEXT, "\n".join(f"body {k}" for k in range(6)))
    assert labels[2] == (DocItemLabel.PAGE_FOOTER, "12")
    assert labels[3][0] == DocItemLabel.TABLE and labels[4][0] == DocItemLabel.PICTURE
    assert labels[5] == (DocItemLabel.SECTION_HEADER, "LAST")              # unordered region last
    child = [t for t in doc.texts if t.text == "Fig. 1 left"]               # row joined with a space
    assert len(child) == 1 and child[0].parent.cref == doc.pictures[0].self_ref   # the picture's child
    footer = [t for t in doc.texts if t.label == DocItemLabel.PAGE_FOOTER][0]
    assert footer.content_layer == ContentLayer.FURNITURE
    assert doc.texts[-1].level == 2
    assert doc.tables[0].data.num_rows == 2 and doc.tables[0].data.table_cells[0].column_header
    p = doc.texts[0].prov[0]
    assert (p.bbox.l, p.bbox.t, p.bbox.r, p.bbox.b, p.charspan) == (100, 100, 900, 160, (0, 9))
    assert doc.pages[1].size.width == 1000


def test_exports_with_and_without_furniture():
    t = page_to_compose()
    t.docling = build_docling(t, name="p1", width=1000, height=1000).export_to_dict()
    md, md_f = to_markdown(t), to_markdown(t, furniture=True)
    assert md.startswith("# THE TITLE") and "\n12\n" not in md and "\n\n12\n\n" in md_f
    assert "| a   | b   |" in md and "#### LAST" not in md and "## LAST" in md
    txt, txt_f = to_text(t), to_text(t, furniture=True)
    assert "12" not in txt.split("\n") and "12" in txt_f.split("\n")
    assert load_docling(t).name == "p1"


def test_blocks_run_and_write_files(tmp_path):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1000, 1000), "white").save(buf, format="PNG")
    doc = new_page_document("p1", buf.getvalue())
    page = page_of(doc)
    page.transcriptions["ocr"] = page_to_compose()
    set_page(doc, page, "ocr")
    out = list(PageExportsWriter(str(tmp_path), formats=("md", "txt", "json"), suffix=".x", furniture=True).run(
        ComposePage().run(Typography().run(iter([doc])))))
    t = page_of(out[0]).transcriptions["ocr"]
    assert t.docling["name"] == "p1" and t.model[-1].step == "typography"
    assert (tmp_path / "p1.x.md").read_text().startswith("# THE TITLE")
    assert "12" in (tmp_path / "p1.x.txt").read_text()
    assert Page.model_validate_json(Page.model_dump_json(page_of(out[0]))) == page_of(out[0])


# --------------------------------------------------------------- reflow
def test_reflow_joins_rows_removes_division_marks_and_continues_regions():
    from linecaster.reflow import Stats

    rid, rid2 = "text_0", "text_1"
    t = page_with([region(rid, "text", 100, 100, 800, 200, 0), region(rid2, "text", 100, 400, 800, 100, 1),
                   region("number_2", "page_footer", 450, 900, 40, 20, 2, raw="number")], [
        line(rid, 0, 100, 100, 800, 20, "The nest is built of dead gras-"),
        line(rid, 1, 100, 130, 800, 20, "ses and bents, and the lining"),
        line(rid, 2, 140, 160, 760, 20, "A new paragraph starts indented and"),
        line(rid, 3, 100, 190, 800, 20, "runs to the end of the column with"),
        line(rid2, 0, 100, 400, 800, 20, "its last words here."),
        line("number_2", 0, 450, 900, 40, 20, "12")])
    stats = Stats()
    doc = build_docling(t, "p", 1000, 1000, text="reflow", stats=stats)
    texts = [x.text for x in doc.texts]
    assert texts[0] == "The nest is built of dead grasses and bents, and the lining"
    assert texts[1] == "A new paragraph starts indented and runs to the end of the column with its last words here."
    assert texts[2] == "12" and len(texts) == 3
    assert (stats.marks_removed, stats.continuations) == (1, 1)
    assert [p.charspan for p in doc.texts[1].prov] == [(0, 35), (36, 70), (71, 91)]   # one entry per row, across regions
