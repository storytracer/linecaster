"""Document exports (html, doclang, docling's JSON formatting), per-page sections and dividers, line-level
detail, layout plots, the single-region layout and ImageFolderReader's item and sequence options."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from linecaster.blocks.base.page import page_of
from linecaster.blocks.binding.item import BindItem
from linecaster.blocks.composition.composer import Composer
from linecaster.blocks.composition.typographer import Typographer
from linecaster.blocks.layout.single_region import SingleRegionLayout
from linecaster.blocks.lines.assigner import LineAssigner
from linecaster.blocks.readers.images import ImageFolderReader
from linecaster.blocks.writers.files import PageExportsWriter, PageFilesWriter
from linecaster.blocks.writers.items import ItemExportsWriter
from linecaster.data.transcription import Line, Transcription
from linecaster.formats import from_alto, from_hocr, from_page
from linecaster.formats.docling import (EXPORT_FORMATS, REGION_MAP_KEY, build_docling, export, to_doclang, to_html,
                                        to_json)

from conftest import line, page_doc, page_t, page_to_compose, region


def _composed_doc(**kw):
    return list(Composer(**kw).run(Typographer().run(iter([page_doc()]))))


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
    t.lines[0].text = "THE TITLE ſ ä"
    doc = build_docling(t, name="p1", width=1000, height=1000)
    doc.save_as_json(tmp_path / "ref.json")
    assert to_json(doc) == (tmp_path / "ref.json").read_text(encoding="utf-8")
    assert to_json(doc.export_to_dict()) == to_json(doc)


def test_page_writers_write_every_document_format(tmp_path: Path):
    docs = _composed_doc()
    fmts = ("md", "txt", "html", "doclang", "json")
    list(PageExportsWriter(str(tmp_path / "a"), formats=fmts, suffix=".x").run(iter(docs)))
    list(PageFilesWriter(str(tmp_path / "b"), formats=fmts, suffix=".x", bucket_by_item=False).run(iter(docs)))
    for fmt in fmts:
        name = f"p1.x.{EXPORT_FORMATS[fmt]}"
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name
    assert (tmp_path / "a" / "p1.x.doclang.xml").read_text().startswith("<doclang")
    assert (tmp_path / "a" / "p1.x.html").read_text().lstrip().lower().startswith("<!doctype html>")


def test_sections_and_dividers_per_page(tmp_path: Path):
    docs = _composed_doc(sections=True)
    t = page_of(docs[0]).transcriptions["ocr"]
    groups = [g for g in t.docling["groups"] if g["label"] == "section"]
    assert [g["name"] for g in groups] == ["THE TITLE", "LAST"]
    region_of = t.extra[REGION_MAP_KEY]
    assert set(region_of.values()) >= {"1:doc_title_0", "1:text_1"}
    list(PageFilesWriter(str(tmp_path), formats=("md",), bucket_by_item=False, dividers=True).run(iter(docs)))
    list(PageFilesWriter(str(tmp_path), formats=("md",), suffix=".plain", bucket_by_item=False).run(iter(docs)))
    with_rules, plain = (tmp_path / "p1.md").read_text(), (tmp_path / "p1.plain.md").read_text()
    assert with_rules.count("\n\n---\n\n") == 4 and "\n\n---\n\n" not in plain
    assert with_rules.replace("\n\n---\n\n", "\n\n") == plain
    list(PageExportsWriter(str(tmp_path / "e"), formats=("md",), dividers=True).run(iter(docs)))
    assert (tmp_path / "e" / "p1.md").read_text() == with_rules


def test_line_detail_drops_the_words(tmp_path: Path):
    t = Transcription(regions=[region("text_0", "text", 10, 10, 300, 40, 0)],
                      lines=[line("text_0", 0, 12, 12, 280, 30, "zwei Worte")])
    t.lines[0].words = []
    from linecaster.data.transcription import Word

    t.lines[0].words = [Word(id="w0", text="zwei", bbox=[12, 12, 100, 30], confidence=0.9),
                        Word(id="w1", text="Worte", bbox=[130, 12, 160, 30], confidence=0.8)]
    docs = [page_doc(t=t, item=None)]
    list(PageFilesWriter(str(tmp_path / "w"), formats=("hocr", "alto", "page")).run(iter(docs)))
    list(PageFilesWriter(str(tmp_path / "l"), formats=("hocr", "alto", "page"), detail="line").run(iter(docs)))
    for name, reader in (("p1.hocr", from_hocr), ("p1.alto.xml", from_alto), ("p1.page.xml", from_page)):
        word, ln = reader((tmp_path / "w" / name).read_bytes()), reader((tmp_path / "l" / name).read_bytes())
        assert [w.text for w in word.lines[0].words] == ["zwei", "Worte"], name
        assert ln.lines[0].text == "zwei Worte" and not ln.lines[0].words, name
    assert len(t.lines[0].words) == 2                      # the transcription itself is untouched
    with pytest.raises(ValueError):
        PageFilesWriter(str(tmp_path), detail="glyph")


def test_layout_plot(tmp_path: Path):
    docs = _composed_doc()
    list(PageFilesWriter(str(tmp_path), formats=("plot",), suffix=".x", bucket_by_item=False).run(iter(docs)))
    with Image.open(tmp_path / "p1.x.layout.jpg") as im:
        assert im.format == "JPEG" and im.size == (1000, 1000)
        assert im.convert("RGB").getpixel((101, 101)) != (255, 255, 255)     # the title region's outline


def test_single_region_layout_takes_every_line():
    t = Transcription(lines=[Line(id="d0", polygon=[[10, 10], [200, 10], [200, 30], [10, 30]], bbox=[10, 10, 190, 20]),
                             Line(id="d1", polygon=[[10, 50], [200, 50], [200, 70], [10, 70]], bbox=[10, 50, 190, 20])])
    out = list(LineAssigner().run(SingleRegionLayout().run(iter([page_doc(t=t, item=None)]))))
    t = page_of(out[0]).transcriptions["ocr"]
    assert [(r.id, r.label, r.bbox, r.reading_order) for r in t.regions] == [("page", "text", [0, 0, 1000, 1000], 0)]
    assert [(ln.id, ln.region_id, ln.row) for ln in t.lines] == [("page_l0", "page", 0), ("page_l1", "page", 1)]


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
    with pytest.raises(ValueError):
        ImageFolderReader(str(tmp_path), item_id="x", item_from_parent=True)


def test_item_exports_html_doclang_json(tmp_path: Path):
    docs = []
    for n in (1, 2):
        t = page_t(n, [f"Page {n} text."], heading="Chapter" if n == 1 else None)
        d = page_doc(page_id=f"p{n}", item="book", t=t, seq=n)
        docs.append(d)
    items = list(BindItem(text="lines", sections=True).run(iter(docs)))
    list(ItemExportsWriter(str(tmp_path), formats=tuple(EXPORT_FORMATS), suffix=".x").run(iter(items)))
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
    t.lines[1].text = "a longer first row"
    doc = build_docling(t, name="p1", width=1000, height=1000, text="reflow")
    before = doc.export_to_dict()
    to_doclang(doc)
    assert doc.export_to_dict() == before
