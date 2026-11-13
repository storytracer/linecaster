"""Retyper and page composition (the post-recognition CPU blocks)."""
from __future__ import annotations

import pytest

from linecaster.blocks.base.page import new_page_document, page_of, set_page
from linecaster.blocks.composition.composer import Composer
from linecaster.blocks.composition.typographer import Typographer
from linecaster.blocks.writers.files import PageFileWriter
from linecaster.data.page import Page
from linecaster.formats.docling import build_docling, to_markdown, to_text
from linecaster.text.typography import retype

from conftest import body_region, line, page_to_compose, page_with, recomposed, region


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
    assert t.heading_level("doc_title_0") == 1                      # 3.0x
    assert t.label("section_header_2") == "text" and t.heading_level("section_header_2") is None   # 1.1x: demoted
    assert t.label("section_header_3") == "section_header" and t.heading_level("section_header_3") == 2   # 1.8x
    assert (stats.leveled, stats.demoted) == (2, 1)
    # the layout's own classification stays; typography's counts
    assert t.role("section_header_2", precedence=["layout"]) == "heading" and t.role("section_header_2") == "paragraph"
    assert t.annotators[-1].step == "typography"


def test_headline_split_off_a_body_region():
    rid = "text_0"
    r = region(rid, "text", 100, 100, 800, 400, 0)
    lines = [line(rid, 0, 100, 100, 800, 50, "HEADLINE"), line(rid, 1, 100, 170, 800, 20, "body a"),
             line(rid, 2, 100, 200, 800, 20, "body b"), line(rid, 3, 100, 230, 800, 20, "body c")]
    other, ol = body_region("text_1", 1, 600)
    t = page_with([r, other], lines + ol)
    stats = retype(t)
    assert stats.split == 1
    assert [x.id for x in t.regions] == [x.id for x in t.ordered_regions()] == ["text_0_head", "text_0", "text_1"]
    head = t.region("text_0_head")
    assert t.label(head.id) == "section_header" and head.label == "text/split" and t.heading_level(head.id) == 1  # 50 / 20 = 2.5
    assert head.parent == "text_0" and head.annotator == len(t.annotators) - 1
    assert head.box == [100.0, 100.0, 800.0, 50.0]
    assert t.region("text_0").box == [100.0, 100.0, 800.0, 400.0]      # the body region keeps its box
    moved = [ln for ln in t.lines if t.region_of(ln) == "text_0_head"]
    assert [ln.id for ln in moved] == ["text_0_l0"] and moved[0].region == "text_0"   # line ids stay; a part_of link
    assert [t.text_of(ln) for ln in t.ordered_lines()][:2] == ["HEADLINE", "body a"]


def test_drop_capital_glued_to_its_paragraph():
    b, bl = body_region("text_1", 1, 300)
    bl[0]["text"] = "ARLY in the morning"
    drop = region("drop_0", "text", 40, 290, 55, 60, 0, raw="drop-capital")
    t = page_with([drop, b], [line("drop_0", 0, 40, 290, 55, 60, "E"), *bl])
    stats = retype(t)
    assert stats.drop_capitals == 1
    assert t.order("regions").regions == ["text_1"] and t.status("drop_0") == "removed"
    first = t.line("text_1_l0")
    assert t.text_of(first, ("nfc", "joined")) == "EARLY in the morning" and first.reading.text == "ARLY in the morning"
    (joined,) = [e for e in t.edits if e.kind == "joined"]
    assert joined.target == "text_1_l0" and joined.derived_from == ["drop_0_l0"]
    assert t.region_of("drop_0_l0") == "drop_0"                          # the drop capital keeps its line
    assert "drop_0_l0" not in t.order("lines").lines and "E" not in t.text.split("\n")
    (removed,) = t.classifications_of("drop_0", "status")
    assert removed.typography__reason == "drop capital merged into text_1_l0"


@pytest.mark.parametrize("conf, kept", [(0.98, True), (0.74, False)])
def test_uncertain_page_numbers_dropped(conf, kept):
    b, bl = body_region("text_1", 1, 300)
    num = region("number_0", "page_header", 450, 40, 40, 20, 0, raw="number")
    head = region("header_2", "page_header", 100, 40, 300, 20, 2, raw="header")   # a running head: never dropped
    t = page_with([num, b, head], [line("number_0", 0, 450, 40, 40, 20, "12", conf=conf), *bl,
                                    line("header_2", 0, 100, 40, 300, 20, "THE BIRDS", conf=0.1)])
    stats = retype(t)
    assert (t.status("number_0") is None) is kept and t.region("number_0") is not None
    assert stats.numbers_dropped == (0 if kept else 1)
    assert t.status("header_2") is None
    if not kept:
        (d,) = t.classifications_of("number_0", "status")
        assert d.typography__reason == "uncertain page number" and d.confidence == pytest.approx(0.74)
        assert t.order("regions").regions == ["text_1", "header_2"] and "12" not in t.text.split("\n")


def test_page_number_confidence_is_character_weighted():
    num = region("number_0", "page_footer", 450, 900, 80, 20, 0, raw="number")
    t = page_with([num], [line("number_0", 0, 450, 900, 30, 20, "1", row=0, conf=0.2),
                          line("number_0", 1, 490, 900, 40, 20, "234", row=0, conf=0.95)])
    retype(t)                       # (0.2*1 + 0.95*3) / 4 = 0.7625 >= 0.75: kept
    assert t.status("number_0") is None


# ------------------------------------------------------------- document


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
    doc = build_docling(page_to_compose(), name="p1", width=1000, height=1000)
    md, md_f = to_markdown(doc), to_markdown(doc, furniture=True)
    assert md.startswith("# THE TITLE") and "\n12\n" not in md and "\n\n12\n\n" in md_f
    assert "| a   | b   |" in md and "#### LAST" not in md and "## LAST" in md
    txt, txt_f = to_text(doc), to_text(doc, furniture=True)
    assert "12" not in txt.split("\n") and "12" in txt_f.split("\n")
    assert doc.name == "p1"


def test_blocks_run_and_write_files(tmp_path):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1000, 1000), "white").save(buf, format="PNG")
    doc = new_page_document("p1", buf.getvalue())
    page = page_of(doc)
    page.transcriptions["ocr_new"] = page_to_compose()
    set_page(doc, page, "ocr_new")
    out = list(PageFileWriter(str(tmp_path), formats=("md", "txt", "json"), suffix=".x", furniture=True,
                              bucket_by_item=False).run(
        Composer("docling-composition@1").run(Typographer("ratios@1").run(iter([doc])))))
    t = page_of(out[0]).transcriptions["ocr_new"]
    assert out[0].metadata["docling"]["name"] == "p1" and t.annotators[-1].step == "typography"   # composing adds none
    a = t.annotators[-1]
    assert (a.kind, a.engine, a.preset) == ("rule", "typography.ratios.v1", "ratios@1")
    assert a.measurements["leveled"] == 2 and {"seconds", "datetime"} <= set(a.measurements)
    assert (tmp_path / "p1.x.md").read_text().startswith("# THE TITLE")
    assert "12" in (tmp_path / "p1.x.txt").read_text()
    assert Page.model_validate_json(Page.model_dump_json(page_of(out[0]))) == page_of(out[0])


# -------------------------------------------------------- recomposition
def test_reflow_joins_rows_removes_division_marks_and_continues_regions():
    rid, rid2 = "text_0", "text_1"
    t = page_with([region(rid, "text", 100, 100, 800, 200, 0), region(rid2, "text", 100, 400, 800, 100, 1),
                   region("number_2", "page_footer", 450, 900, 40, 20, 2, raw="number")], [
        line(rid, 0, 100, 100, 800, 20, "The nest is built of dead gras-"),
        line(rid, 1, 100, 130, 800, 20, "ses and bents, and the lining"),
        line(rid, 2, 140, 160, 760, 20, "A new paragraph starts indented and"),
        line(rid, 3, 100, 190, 800, 20, "runs to the end of the column with"),
        line(rid2, 0, 100, 400, 800, 20, "its last words here."),
        line("number_2", 0, 450, 900, 40, 20, "12")])
    recomposed(t)
    doc = build_docling(t, "p", 1000, 1000)
    texts = [x.text for x in doc.texts]
    assert texts[0] == "The nest is built of dead grasses and bents, and the lining"
    assert texts[1] == "A new paragraph starts indented and runs to the end of the column with its last words here."
    assert texts[2] == "12" and len(texts) == 3
    m = t.annotators[-1].measurements
    assert (m["marks_removed"], m["continuations"], m["paragraphs"]) == (1, 1, 3)
    assert [p.charspan for p in doc.texts[1].prov] == [(0, 35), (36, 70), (71, 91)]   # one entry per row, across regions
