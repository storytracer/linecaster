"""Document exports (HTML, Markdown, text, the document's JSON), per-page sections and dividers, line-level detail,
layout plots, the single-region layout and ImageFolderReader's item and sequence options."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from linecaster.blocks.base.page import page_of
from linecaster.blocks.binding import Binder
from linecaster.blocks.composition.composer import Composer
from linecaster.blocks.composition.typographer import Typographer
from linecaster.blocks.layout import LayoutDetector
from linecaster.blocks.lines.assigner import LineAssigner
from linecaster.blocks.readers.images import ImageFolderReader
from linecaster.blocks.writers.files import PageFileWriter
from linecaster.blocks.writers.items import ItemDocumentWriter
from linecaster.data.transcription import Annotator, Description, Transcription, Word
from linecaster.document import (DOCUMENT_KEY, EXPORT_FORMATS, DocumentBuilder, build_document, export, from_json,
                                 load_document, to_html, to_json)
from linecaster.errors import PipelineConfigError
from linecaster.formats import from_alto, from_hocr, from_page

from conftest import line, page_doc, page_t, page_to_compose, page_with, recomposed, region


def _composed_doc(**options):
    return list(Composer("linked-composition@1", options=options).run(Typographer("ratios@1").run(iter([page_doc()]))))


def test_html_follows_the_furniture_layer():
    t = page_to_compose()
    doc = build_document(t, name="p1", width=1000, height=1000)
    html, html_f = to_html(doc), to_html(doc, furniture=True)
    assert html.startswith("<!DOCTYPE html>") and "<h1>THE TITLE</h1>" in html and "<title>p1</title>" in html
    assert ">12<" not in html and '<footer role="doc-pagefooter"><p>12</p></footer>' in html_f
    for fmt in EXPORT_FORMATS:
        assert export(doc, fmt) == export(doc.model_dump(by_alias=True), fmt)
    with pytest.raises(ValueError):
        export(doc, "pdf")


def test_json_is_the_complete_document():
    """The JSON holds every layer and origin, and reads back to the same document."""
    t = page_to_compose()
    t.lines[0].reading.text = "THE TITLE ſ ä"
    doc = build_document(t, name="p1", width=1000, height=1000)
    data = json.loads(to_json(doc))
    assert data["schema"] == "linecaster.document/1" and "ſ ä" in to_json(doc)
    assert {b["layer"] for b in data["blocks"]} == {"body", "furniture"}
    assert from_json(to_json(doc)) == doc and to_json(doc.model_dump(by_alias=True)) == to_json(doc)


def test_page_writers_write_every_document_format(tmp_path: Path):
    docs = _composed_doc()
    fmts = ("md", "txt", "html", "json")
    list(PageFileWriter(str(tmp_path / "a"), formats=fmts, suffix=".x", bucket_by_item=False).run(iter(docs)))
    data = docs[0].metadata[DOCUMENT_KEY]                 # the Composer's document
    for fmt in fmts:
        name = f"p1.x.{EXPORT_FORMATS[fmt]}"
        assert (tmp_path / "a" / name).read_bytes() == export(load_document(data), fmt).encode("utf-8"), name
    assert (tmp_path / "a" / "p1.x.html").read_text().lstrip().lower().startswith("<!doctype html>")


def test_sections_and_dividers_per_page(tmp_path: Path):
    docs = _composed_doc(sections=True)
    doc = load_document(docs[0].metadata[DOCUMENT_KEY])
    assert [b.text for b in doc.blocks if b.section == b.id] == ["THE TITLE", "LAST"]
    assert {o.region for b in doc.blocks for o in b.origins} >= {"doc_title_0", "text_1"}
    list(PageFileWriter(str(tmp_path), formats=("md",), bucket_by_item=False, dividers=True).run(iter(docs)))
    list(PageFileWriter(str(tmp_path), formats=("md",), suffix=".plain", bucket_by_item=False).run(iter(docs)))
    with_rules, plain = (tmp_path / "p1.md").read_text(), (tmp_path / "p1.plain.md").read_text()
    assert with_rules.count("\n\n---\n\n") == 4 and "\n\n---\n\n" not in plain
    assert with_rules.replace("\n\n---\n\n", "\n\n") == plain
    list(PageFileWriter(str(tmp_path / "e"), formats=("md",), bucket_by_item=False, dividers=True,
                        text_fallback=False).run(iter(docs)))
    assert (tmp_path / "e" / "p1.md").read_text() == with_rules


def test_line_detail_drops_the_words(tmp_path: Path):
    t = page_with([region("text_0", "text", 10, 10, 300, 40, 0)], [line("text_0", 0, 12, 12, 280, 30, "zwei Worte")])
    t.lines[0].reading.words = [Word(id="w0", text="zwei", box=[12, 12, 100, 30], confidence=0.9),
                                Word(id="w1", text="Worte", box=[130, 12, 160, 30], confidence=0.8)]
    docs = [page_doc(t=t, item=None)]
    list(PageFileWriter(str(tmp_path / "w"), formats=("hocr", "alto", "page")).run(iter(docs)))
    list(PageFileWriter(str(tmp_path / "l"), formats=("hocr", "alto", "page"), detail="line").run(iter(docs)))
    for name, reader in (("p1.hocr", from_hocr), ("p1.alto.xml", from_alto), ("p1.page.xml", from_page)):
        word, ln = reader((tmp_path / "w" / name).read_bytes()), reader((tmp_path / "l" / name).read_bytes())
        assert [w.text for w in word.lines[0].reading.words] == ["zwei", "Worte"], name
        assert [word.lines[0].word_id(k) for k in range(2)] == ["w0", "w1"], name
        assert ln.text_of(ln.lines[0]) == "zwei Worte" and not ln.lines[0].reading.words, name
    assert len(t.lines[0].reading.words) == 2              # the transcription itself is untouched
    with pytest.raises(PipelineConfigError):
        PageFileWriter(str(tmp_path), detail="glyph")


def test_layout_plot(tmp_path: Path):
    docs = _composed_doc()
    list(PageFileWriter(str(tmp_path), formats=("plot",), suffix=".x", bucket_by_item=False).run(iter(docs)))
    with Image.open(tmp_path / "p1.x.layout.jpg") as im:
        assert im.format == "JPEG" and im.size == (1000, 1000)
        assert im.convert("RGB").getpixel((101, 101)) != (255, 255, 255)     # the title region's outline


def test_single_region_layout_takes_every_line():
    t = Transcription()
    a = t.add_annotator(Annotator(step="lines", name="test"))
    t.add_line(a, "d0", [10, 10, 190, 20], [[10, 10], [200, 10], [200, 30], [10, 30]])
    t.add_line(a, "d1", [10, 50, 190, 20], [[10, 50], [200, 50], [200, 70], [10, 70]])
    out = list(LineAssigner().run(LayoutDetector("single-region@1").run(iter([page_doc(t=t, item=None)]))))
    t = page_of(out[0]).transcriptions["ocr_new"]
    assert [(r.id, t.label(r.id), r.box, t.region_ranks().get(r.id)) for r in t.regions] == [
        ("page", "text", [0, 0, 1000, 1000], 0)]
    assert [(ln.id, t.region_of(ln), t.rows()[ln.id]) for ln in t.ordered_lines()] == [("d0", "page", 0),
                                                                                       ("d1", "page", 1)]
    step, assigned = t.annotators[-2:]
    assert (step.step, step.engine, step.preset) == ("layout", "layout.single-region.v1", "single-region@1")
    assert assigned.step == "assignment" and set(assigned.measurements) == {"seconds", "datetime"}
    assert step.settings == {"label": "text", "region_id": "page"}


def test_single_region_layout_runs_in_process_only():
    from linecaster.backends import InProcess
    from linecaster.catalog.registry import engine_spec
    from linecaster.errors import CatalogError
    from linecaster.runtime import run

    with pytest.raises(CatalogError, match="in the pipeline's process only"):
        engine_spec("single-region@1", served=True)              # linecaster serve refuses it
    with pytest.raises(PipelineConfigError, match="is a layout preset"):
        from linecaster.blocks.lines import LineDetector

        LineDetector("single-region@1")
    # a served run keeps it in the pipeline's process, and starts no model server for it alone
    ap = run.parser(None)
    a = run.check(ap, ap.parse_args(["images", "out", "--backend", "served"]))
    backends, servers = run.engines(a, [{"name": "layout", "preset": "single-region"}], "x.py")
    assert isinstance(backends["layout"], InProcess) and backends["layout"].preset == "single-region@1"
    assert servers == []


def _png(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 20), "white").save(path)


def test_image_folder_reader_item_and_sequence(tmp_path: Path):
    for name in ("b/02.png", "b/01.png", "a/03.png", "a/01x.png"):
        _png(tmp_path / name)
    pages = [page_of(d) for d in ImageFolderReader(str(tmp_path), item_from_parent=True, sequence=True).run()]
    assert [(p.item_id, p.page_id, p.sequence) for p in pages] == [("a", "01x", 1), ("a", "03", 2), ("b", "01", 1),
                                                                  ("b", "02", 2)]
    pages = [page_of(d) for d in ImageFolderReader(str(tmp_path), item_id="book", sequence=True).run(rank=1, world_size=2)]
    assert [(p.item_id, p.page_id, p.sequence) for p in pages] == [("book", "03", 2), ("book", "02", 4)]
    assert all(p.sequence is None for p in map(page_of, ImageFolderReader(str(tmp_path)).run()))
    with pytest.raises(PipelineConfigError):
        ImageFolderReader(str(tmp_path), item_id="x", item_from_parent=True)


def test_item_exports_every_format(tmp_path: Path):
    docs = []
    for n in (1, 2):
        t = page_t(n, [f"Page {n} text."], heading="Chapter" if n == 1 else None)
        d = page_doc(page_id=f"p{n}", item="book", t=t, seq=n)
        docs.append(d)
    items = list(Composer("linked-composition@1", unit="item", options={"sections": True}).run(Binder().run(iter(docs))))
    list(ItemDocumentWriter(str(tmp_path), formats=tuple(EXPORT_FORMATS), suffix=".x").run(iter(items)))
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == sorted(f"book.x.{ext}" for ext in EXPORT_FORMATS.values())
    doc = load_document(items[0].metadata[DOCUMENT_KEY])
    assert (tmp_path / "book.x.json").read_text() == to_json(doc)
    assert json.loads((tmp_path / "book.x.json").read_text())["name"] == "book"
    body = doc.layer("body")
    assert [(b.kind, b.section) for b in body] == [("heading", "b0"), ("paragraph", "b0"), ("paragraph", "b0")]
    assert [o.page for b in body for o in b.origins if b.kind == "paragraph"] == [1, 2]


def test_origins_are_clamped_to_the_page():
    t = page_to_compose()
    t.regions[4].polygon = [[-18, -3], [300, -3], [300, 1034], [-18, 1034]]     # the picture, past the page edge
    doc = build_document(t, name="p1", width=1000, height=1000)
    assert next(b for b in doc.blocks if b.kind == "picture").origins[0].box == [0, 0, 300, 1000]
    assert t.regions[4].polygon[0] == [-18, -3]                                    # the layout itself is untouched


def test_tables_follow_the_cells():
    """A table block's grid holds its cells as they are (offsets, spans, header and section flags, text); HTML gives
    the spans and header cells."""
    from linecaster.data.transcription import Cell, Table
    from linecaster.document import table_html

    t = page_to_compose()
    t.tables = [Table(annotator=0, target="table_3", num_rows=2, num_cols=3, cells=[
        Cell(start_row=0, end_row=1, start_col=0, end_col=2, text="Ort und Zeit", column_header=True),
        Cell(start_row=0, end_row=1, start_col=2, end_col=3, text="n", column_header=True),
        Cell(start_row=1, end_row=2, start_col=0, end_col=1, text="Köln", row_header=True),
        Cell(start_row=1, end_row=2, start_col=1, end_col=3, text="Sommer", row_section=True)])]
    block = next(b for b in build_document(t).blocks if b.kind == "table")
    assert block.grid.cells == t.tables[0].cells
    assert table_html(block) == ('<table><tr><th colspan="2">Ort und Zeit</th><th>n</th></tr>'
                                 '<tr><th>Köln</th><td colspan="2">Sommer</td></tr></table>')


@pytest.mark.parametrize("in_cell, cells", [
    (False, [(0, 0, "a"), (0, 1, "b"), (1, 0, ""), (1, 1, "on"), (2, 0, "c"), (2, 1, "d")]),     # its rows follow
    (True, [(0, 0, "a"), (0, 1, "b on"), (1, 0, "c"), (1, 1, "d")]),     # its top row goes on with the last, by column
])
def test_a_table_continues_across_pages(in_cell, cells):
    """A table a page's ``runs_into`` link leaves to the next is one table block in the item's document; where the
    next page goes on in the middle of a cell (a link between cells), its top row joins the last."""
    from linecaster.data import Link
    from linecaster.data.transcription import Cell, Table

    def page(rows):
        t = page_to_compose()
        t.tables = [Table(annotator=0, target="table_3", num_rows=len(rows), num_cols=2, cells=[
            Cell(start_row=i, end_row=i + 1, start_col=j, end_col=j + 1, text=x)
            for i, row in enumerate(rows) for j, x in enumerate(row)])]
        return t

    first, second = page([["a", "b"]]), page([["", "on"], ["c", "d"]])
    first.links.append(Link(annotator=0, kind="runs_into", source="table_3", target="p2#table_3"))
    second.links.append(Link(annotator=0, kind="continues", source="table_3", target="p1#table_3"))
    if in_cell:
        first.links.append(Link(annotator=0, kind="runs_into", source="table_3/r0c1", target="p2#table_3/r0c1"))
        second.links.append(Link(annotator=0, kind="continues", source="table_3/r0c1", target="p1#table_3/r0c1"))
    b = DocumentBuilder("item")
    for k, t in enumerate((first, second)):
        b.add_page(t, 1000, 1000, page_id=f"p{k + 1}")
    tables = [x for x in b.build().blocks if x.kind == "table"]
    assert len(tables) == 1 and len(tables[0].origins) == 2
    assert [(c.start_row, c.start_col, c.text) for c in tables[0].grid.cells] == cells


def test_a_cell_continued_on_the_next_page_keeps_its_formulas():
    """A cell that goes on onto the next page joins its text there, and the formulas of both parts stay on theirs."""
    from linecaster.data import Link
    from linecaster.data.transcription import Cell, Table

    def page(text, formulas):
        t = page_to_compose()
        t.tables = [Table(annotator=0, target="table_3", num_rows=1, num_cols=1, cells=[
            Cell(start_row=0, end_row=1, start_col=0, end_col=1, text=text, formulas=formulas)])]
        return t

    first, second = page("$x$ and", [[0, 3]]), page("$y$ on", [[0, 3]])
    first.links += [Link(annotator=0, kind="runs_into", source="table_3", target="p2#table_3"),
                    Link(annotator=0, kind="runs_into", source="table_3/r0c0", target="p2#table_3/r0c0")]
    second.links += [Link(annotator=0, kind="continues", source="table_3", target="p1#table_3"),
                     Link(annotator=0, kind="continues", source="table_3/r0c0", target="p1#table_3/r0c0")]
    b = DocumentBuilder("item")
    for k, t in enumerate((first, second)):
        b.add_page(t, 1000, 1000, page_id=f"p{k + 1}")
    cell = next(x for x in b.build().blocks if x.kind == "table").grid.cells[0]
    assert cell.text == "$x$ and $y$ on" and [cell.text[a:e] for a, e in cell.formulas] == ["$x$", "$y$"]


def _parts(doc):
    return [(b.kind, b.text or None, b.layer) for b in doc.blocks]


def test_the_rendering_policy_places_the_regions():
    """Layers come from the policy: furniture for page headers and footers by default, nothing for removed regions
    (nor their lines); another policy puts a role elsewhere. Descriptions are never text."""
    from linecaster.data.policy import RenderingPolicy, RenderingRule

    t = page_to_compose()
    a = t.add_annotator(Annotator(kind="rule", step="typography", name="ratios"))
    t.classify(a, "section_header_6", "status", "removed")
    t.descriptions.append(Description(annotator=0, target="image_4", text="a drawing of a flower"))
    parts = _parts(build_document(t, name="p1", width=1000, height=1000))
    assert ("page_footer", "12", "furniture") in parts and ("title", "THE TITLE", "body") in parts
    assert not any(text in ("LAST", "a drawing of a flower") for _, text, _ in parts)
    notes = RenderingPolicy(id="test", rules=[RenderingRule(role="title", to="notes"),
                                              RenderingRule(role="footer", to="none")])
    parts = _parts(build_document(t, name="p1", width=1000, height=1000, policy=notes))
    assert ("title", "THE TITLE", "notes") in parts and not any(text == "12" for _, text, _ in parts)


def test_paragraphs_continue_by_their_links():
    """A paragraph that runs into another (``runs_into``, ``continues`` links; on another page:
    ``<page_id>#<id>``) is one block; without the links, two."""
    from linecaster.data.transcription import Link

    def item(*links):
        pages = [recomposed(page_t(1, ["The first page ends with a long sen-"])),
                 recomposed(page_t(2, ["tence that ends here."]))]
        for t in pages:
            t.links = [ln for ln in t.links if ln.kind not in ("runs_into", "continues")]
        for k, kind, source, target in links:
            pages[k].links.append(Link(annotator=len(pages[k].annotators) - 1, kind=kind, source=source, target=target))
        b = DocumentBuilder("book")
        for k, t in enumerate(pages):
            b.add_page(t, 1000, 1000, page_id=f"p{k + 1}")
        return [x.text for x in b.build().blocks if x.kind == "paragraph"]

    assert item() == ["The first page ends with a long sen-", "tence that ends here."]
    joined = item((0, "runs_into", "text_1_p0", "p2#text_1_p0"), (1, "continues", "text_1_p0", "p1#text_1_p0"))
    assert joined == ["The first page ends with a long sen-tence that ends here."]


def test_regions_continue_by_their_links():
    """Without a recomposition (a transcription whose regions are its paragraphs, as an imported ground truth), a text
    region that continues another is that one's block: a division mark before a lowercase letter removed, else a
    space; the block has an origin per page."""
    from linecaster.data.transcription import Link

    def item(first, second, linked=True):
        pages = [page_t(1, [first]), page_t(2, [second])]
        if linked:
            pages[0].links.append(Link(annotator=0, kind="runs_into", source="text_1", target="p2#text_1"))
            pages[1].links.append(Link(annotator=0, kind="continues", source="text_1", target="p1#text_1"))
        b = DocumentBuilder("item")
        for k, t in enumerate(pages):
            b.add_page(t, 1000, 1000, page_id=f"p{k + 1}")
        return [x for x in b.build().blocks if x.kind == "paragraph"]

    assert [x.text for x in item("A long sen-", "tence ends.", linked=False)] == ["A long sen-", "tence ends."]
    joined = item("A long sen-", "tence ends.")
    assert [x.text for x in joined] == ["A long sentence ends."]
    assert [(o.page, o.span) for o in joined[0].origins] == [(1, [0, 11]), (2, [10, 21])]
    assert [x.text for x in item("runs on to the", "next page.")] == ["runs on to the next page."]
    assert [x.text for x in item("the well-", "Known name")] == ["the well-Known name"]
    verse = DocumentBuilder("item")                          # a block of several rows goes on with a new row
    pages = [page_t(1, ["The night was dark,", "the wind was cold,"]), page_t(2, ["and all the trees"])]
    pages[0].links.append(Link(annotator=0, kind="runs_into", source="text_1", target="p2#text_1"))
    pages[1].links.append(Link(annotator=0, kind="continues", source="text_1", target="p1#text_1"))
    for k, t in enumerate(pages):
        verse.add_page(t, 1000, 1000, page_id=f"p{k + 1}")
    assert [x.text for x in verse.build().blocks if x.kind == "paragraph"] == [
        "The night was dark,\nthe wind was cold,\nand all the trees"]


def test_the_composer_adds_nothing_to_the_transcription():
    before = page_of(Typographer("ratios@1").run(iter([page_doc()])).__next__()).transcriptions["ocr_new"]
    docs = _composed_doc()
    after = page_of(docs[0]).transcriptions["ocr_new"]
    assert after.model_dump(exclude={"annotators"}) == before.model_dump(exclude={"annotators"})
    assert [a.step for a in after.annotators] == [a.step for a in before.annotators]
    assert docs[0].metadata["document_transcription"] == "ocr_new" and docs[0].metadata[DOCUMENT_KEY]["name"] == "p1"
