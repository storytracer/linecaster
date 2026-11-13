"""Document exports (html, doclang, docling's JSON formatting), per-page sections and dividers, line-level
detail, layout plots, the single-region layout and ImageFolderReader's item and sequence options."""
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
from docling_core.types.doc import ContentLayer

from linecaster.data.transcription import Annotator, Description, Transcription, Word
from linecaster.errors import PipelineConfigError
from linecaster.formats import from_alto, from_hocr, from_page
from linecaster.formats.docling import (DOCUMENT_KEY, EXPORT_FORMATS, REGION_MAP_KEY, build_docling, export,
                                        load_docling, to_doclang, to_html, to_json)

from conftest import line, page_doc, page_t, page_to_compose, page_with, recomposed, region


def _composed_doc(**options):
    return list(Composer("docling-composition@1", options=options).run(Typographer("ratios@1").run(iter([page_doc()]))))


def test_html_and_doclang_follow_docling_and_the_furniture_layer():
    t = page_to_compose()
    doc = build_docling(t, name="p1", width=1000, height=1000)
    html, html_f = to_html(doc), to_html(doc, furniture=True)
    assert html == doc.export_to_html() and "THE TITLE" in html
    assert ">12<" not in html and ">12<" in html_f
    dl = to_doclang(doc)
    assert dl == doc.export_to_doclang(add_named_groups=True)
    assert '<layer value="furniture"/>' in dl                 # DocLang keeps the furniture, marked
    for fmt in EXPORT_FORMATS:
        assert export(doc, fmt) == export(doc.export_to_dict(), fmt)
    with pytest.raises(ValueError):
        export(doc, "pdf")


def test_json_is_formatted_as_docling_saves_it(tmp_path: Path):
    t = page_to_compose()
    t.lines[0].reading.text = "THE TITLE ſ ä"
    doc = build_docling(t, name="p1", width=1000, height=1000)
    doc.save_as_json(tmp_path / "ref.json")
    assert to_json(doc) == (tmp_path / "ref.json").read_text(encoding="utf-8")
    assert to_json(doc.export_to_dict()) == to_json(doc)


def test_page_writers_write_every_document_format(tmp_path: Path):
    docs = _composed_doc()
    fmts = ("md", "txt", "html", "doclang", "json")
    list(PageFileWriter(str(tmp_path / "a"), formats=fmts, suffix=".x", bucket_by_item=False).run(iter(docs)))
    data = docs[0].metadata[DOCUMENT_KEY]                 # the Composer's document
    for fmt in fmts:
        name = f"p1.x.{EXPORT_FORMATS[fmt]}"
        expected = export(data if fmt == "json" else load_docling(data), fmt).encode("utf-8")
        assert (tmp_path / "a" / name).read_bytes() == expected, name
    assert (tmp_path / "a" / "p1.x.doclang.xml").read_text().startswith("<doclang")
    assert (tmp_path / "a" / "p1.x.html").read_text().lstrip().lower().startswith("<!doctype html>")


def test_sections_and_dividers_per_page(tmp_path: Path):
    docs = _composed_doc(sections=True)
    groups = [g for g in docs[0].metadata[DOCUMENT_KEY]["groups"] if g["label"] == "section"]
    assert [g["name"] for g in groups] == ["THE TITLE", "LAST"]
    region_of = docs[0].metadata[REGION_MAP_KEY]
    assert set(region_of.values()) >= {"1:doc_title_0", "1:text_1"}
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


def test_item_exports_html_doclang_json(tmp_path: Path):
    docs = []
    for n in (1, 2):
        t = page_t(n, [f"Page {n} text."], heading="Chapter" if n == 1 else None)
        d = page_doc(page_id=f"p{n}", item="book", t=t, seq=n)
        docs.append(d)
    items = list(Composer("docling-composition@1", unit="item", options={"sections": True}).run(Binder().run(iter(docs))))
    list(ItemDocumentWriter(str(tmp_path), formats=tuple(EXPORT_FORMATS), suffix=".x").run(iter(items)))
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == sorted(f"book.x.{ext}" for ext in EXPORT_FORMATS.values())
    from docling_core.types.doc import DoclingDocument

    doc = DoclingDocument.model_validate(items[0].metadata["docling"])
    assert (tmp_path / "book.x.json").read_text() == to_json(doc)
    assert '<group' in (tmp_path / "book.x.doclang.xml").read_text()
    assert json.loads((tmp_path / "book.x.json").read_text())["name"] == "book"


def test_provenance_is_clamped_to_the_page_as_docling_validates_it():
    from docling_core.types.doc import DoclingDocument

    t = page_to_compose()
    t.regions[4].polygon = [[-18, -3], [300, -3], [300, 1034], [-18, 1034]]     # the picture, past the page edge
    doc = build_docling(t, name="p1", width=1000, height=1000)
    b = doc.pictures[0].prov[0].bbox
    assert (b.l, b.t, b.r, b.b) == (0, 0, 300, 1000)
    assert DoclingDocument.model_validate(doc.export_to_dict()).export_to_dict() == doc.export_to_dict()
    assert t.regions[4].polygon[0] == [-18, -3]                                    # the layout itself is untouched


def test_doclang_export_leaves_the_document_alone():
    t = page_to_compose()
    t.lines[1].reading.text = "a longer first row"
    doc = build_docling(recomposed(t), name="p1", width=1000, height=1000)
    before = doc.export_to_dict()
    to_doclang(doc)
    assert doc.export_to_dict() == before


def test_table_data_round_trip_is_lossless():
    """``table_data`` and ``from_table_data`` invert each other: offsets, spans, header and section flags, text and
    boxes."""
    from linecaster.data.transcription import Cell, Table
    from linecaster.formats.docling import from_table_data, table_data

    table = Table(annotator=2, target="table_3", num_rows=3, num_cols=3, cells=[
        Cell(start_row=0, end_row=1, start_col=0, end_col=2, text="Ort und Zeit", box=[100.0, 600.0, 400.5, 50.25],
             column_header=True),
        Cell(start_row=0, end_row=1, start_col=2, end_col=3, text="n", column_header=True),
        Cell(start_row=1, end_row=3, start_col=0, end_col=1, text="Köln", row_header=True, box=[100, 650, 200, 100]),
        Cell(start_row=1, end_row=2, start_col=1, end_col=3, text="Sommer", row_section=True),
        Cell(start_row=2, end_row=3, start_col=1, end_col=2, text=""),
        Cell(start_row=2, end_row=3, start_col=2, end_col=3, text="2", box=[0.5, 0.25, 0.125, 1.0])])
    data = table_data(table)
    assert [(c.row_span, c.col_span) for c in data.table_cells] == [(1, 2), (1, 1), (2, 1), (1, 2), (1, 1), (1, 1)]
    assert from_table_data(data, 2, "table_3") == table
    assert from_table_data(data, 2, "table_3", html="<table/>").html == "<table/>"


def _parts(doc):
    return [(it.label.value, it.text if hasattr(it, "text") else None, it.content_layer.value)
            for it, _ in doc.iterate_items(included_content_layers=set(ContentLayer))]


def test_the_rendering_policy_places_the_regions():
    """Layers come from the policy: furniture for page headers and footers by default, nothing for removed regions
    (nor their lines); another policy puts a role elsewhere. Descriptions are never text."""
    from linecaster.data.policy import RenderingPolicy, RenderingRule

    t = page_to_compose()
    a = t.add_annotator(Annotator(kind="rule", step="typography", name="ratios"))
    t.classify(a, "section_header_6", "status", "removed")
    t.descriptions.append(Description(annotator=0, target="image_4", text="a drawing of a flower"))
    parts = _parts(build_docling(t, name="p1", width=1000, height=1000))
    assert ("page_footer", "12", "furniture") in parts and ("title", "THE TITLE", "body") in parts
    assert not any(text in ("LAST", "a drawing of a flower") for _, text, _ in parts)
    notes = RenderingPolicy(id="test", rules=[RenderingRule(role="title", to="notes"),
                                              RenderingRule(role="footer", to="none")])
    parts = _parts(build_docling(t, name="p1", width=1000, height=1000, policy=notes))
    assert ("title", "THE TITLE", "notes") in parts and not any(text == "12" for _, text, _ in parts)


def test_paragraphs_continue_by_their_links():
    """A paragraph that runs into another (``runs_into``, ``continues`` links; on another page:
    ``<page_id>#<id>``) is one item; without the links, two."""
    from linecaster.data.transcription import Link
    from linecaster.formats.docling import DocumentBuilder

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
        return [x.text for x in b.build().texts if x.label.value == "text"]

    assert item() == ["The first page ends with a long sen-", "tence that ends here."]
    joined = item((0, "runs_into", "text_1_p0", "p2#text_1_p0"), (1, "continues", "text_1_p0", "p1#text_1_p0"))
    assert joined == ["The first page ends with a long sen-tence that ends here."]


def test_the_composer_adds_nothing_to_the_transcription():
    before = page_of(Typographer("ratios@1").run(iter([page_doc()])).__next__()).transcriptions["ocr_new"]
    docs = _composed_doc()
    after = page_of(docs[0]).transcriptions["ocr_new"]
    assert after.model_dump(exclude={"annotators"}) == before.model_dump(exclude={"annotators"})
    assert [a.step for a in after.annotators] == [a.step for a in before.annotators]
    assert docs[0].metadata["docling_transcription"] == "ocr_new" and docs[0].metadata[DOCUMENT_KEY]["name"] == "p1"
