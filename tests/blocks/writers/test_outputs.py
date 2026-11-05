"""Per-page files (PageFileWriter), item texts with tables and NFC, item text writers."""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest
from lxml import etree

from linecaster.blocks.base.page import page_of
from linecaster.blocks.binding.texts import ItemTexts
from linecaster.blocks.composition.composer import Composer
from linecaster.blocks.composition.typographer import Typographer
from linecaster.blocks.writers.files import PageFileWriter
from linecaster.blocks.writers.items import ItemTextWriter
from linecaster.data.transcription import Line, Region, Transcription
from linecaster.formats import from_alto, from_hocr, from_page
from linecaster.formats.docling import EXPORT_FORMATS, export, load_docling
from linecaster.text import variants as T

from conftest import page_doc

SCHEMAS = Path(__file__).parents[2] / "schemas"


def test_page_files_all_formats_bucketed_and_valid(tmp_path: Path):
    docs = list(Composer().run(Typographer().run(iter([page_doc()]))))
    fmts = ("hocr", "alto", "page", "txt", "md", "json", "transcription")
    out = list(PageFileWriter(str(tmp_path), formats=fmts).run(iter(docs)))
    assert len(out) == 1
    folder = tmp_path / "book1"
    names = sorted(p.name for p in folder.iterdir())
    assert names == sorted(["p1.hocr", "p1.alto.xml", "p1.page.xml", "p1.txt", "p1.md", "p1.json",
                            "p1.transcription.json"])
    t = page_of(out[0]).transcriptions["ocr"]
    for name, reader in (("p1.hocr", from_hocr), ("p1.alto.xml", from_alto), ("p1.page.xml", from_page)):
        assert [ln.text for ln in reader((folder / name).read_bytes()).ordered_lines()] == \
            [ln.text for ln in t.ordered_lines()]
    for name, xsd in (("p1.alto.xml", "alto-4-4.xsd"), ("p1.page.xml", "pagecontent-2019-07-15.xsd")):
        schema = etree.XMLSchema(etree.parse(str(SCHEMAS / xsd)))
        assert schema.validate(etree.parse(str(folder / name))), schema.error_log
    assert (folder / "p1.md").read_text().startswith("# THE TITLE")
    assert json.loads((folder / "p1.json").read_text())["schema_name"] == "DoclingDocument"
    assert json.loads((folder / "p1.transcription.json").read_text())["regions"]


def test_page_files_flat_are_the_document_exports(tmp_path: Path):
    """Flat names with a suffix (squiddleocr's): each file is the document's export byte for byte, as the
    export writer this one replaces wrote them (flat, suffix, furniture)."""
    docs = list(Composer().run(Typographer().run(iter([page_doc()]))))
    list(PageFileWriter(str(tmp_path), formats=("md", "txt", "json"), suffix=".x", furniture=True,
                        bucket_by_item=False).run(iter(docs)))
    t = page_of(docs[0]).transcriptions["ocr"]
    for fmt in ("md", "txt", "json"):
        expected = export(t.docling if fmt == "json" else load_docling(t), fmt, True).encode("utf-8")
        assert (tmp_path / f"p1.x.{EXPORT_FORMATS[fmt]}").read_bytes() == expected, fmt
    assert sorted(p.name for p in tmp_path.iterdir()) == ["p1.x.json", "p1.x.md", "p1.x.txt"]


def test_page_files_without_document_fall_back_to_page_text(tmp_path: Path):
    t = Transcription(lines=[Line(id="l0", reading_order=0, bbox=[10, 10, 100, 20], text="nur Zeilen")])
    out = list(PageFileWriter(str(tmp_path), formats=("txt", "md", "json")).run(iter([page_doc(t=t, item=None)])))
    assert (tmp_path / "p1.txt").read_text() == "nur Zeilen" and (tmp_path / "p1.md").exists()
    assert not (tmp_path / "p1.json").exists() and len(out) == 1
    with pytest.raises(ValueError):
        PageFileWriter(str(tmp_path), formats=("pdf",))


def test_page_files_without_text_fallback_write_only_documents(tmp_path: Path):
    """``text_fallback=False``: a page without a document gets no file of a document format (the export
    writer's behavior), and a page with one gets them all."""
    t = Transcription(lines=[Line(id="l0", reading_order=0, bbox=[10, 10, 100, 20], text="nur Zeilen")])
    fmts = ("md", "txt", "html", "doclang", "json")
    composed = list(Composer().run(Typographer().run(iter([page_doc(page_id="p2", item=None)]))))
    out = list(PageFileWriter(str(tmp_path), formats=fmts, bucket_by_item=False, text_fallback=False).run(
        iter([page_doc(t=t, item=None), *composed])))
    assert len(out) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(f"p2.{EXPORT_FORMATS[f]}" for f in fmts)


def _region(rid, label, order, **kw):
    return Region(id=rid, label=label, polygon=[[0, 0], [1, 0], [1, 1]], bbox=[0, 0, 1, 1], reading_order=order, **kw)


def test_variants_render_tables_and_nfc_input():
    table = {"cells": [{"text": "Ort", "row": 0, "col": 0}, {"text": "Weſen", "row": 0, "col": 1},
                       {"text": "Koͤln", "row": 1, "col": 0}, {"text": "2", "row": 1, "col": 1}]}
    decomposed = unicodedata.normalize("NFD", "Über die Käfer")
    t = Transcription(
        regions=[_region("h", "page_header", 0), _region("a", "text", 1), _region("t", "table", 2, extra={"table": table})],
        lines=[Line(id="h0", region_id="h", reading_order=0, text="KOPF"),
               Line(id="a0", region_id="a", reading_order=1, text=decomposed + " ſind"),
               Line(id="t0", region_id="t", reading_order=2, text="Ort Weſen"),
               Line(id="t1", region_id="t", reading_order=3, text="Köln 2")])
    v = T.variants([t])
    assert v["verbatim_txt"] == "KOPF\nÜber die Käfer ſind\n| Ort | Weſen |\n|---|---|\n| Koͤln | 2 |"
    assert unicodedata.is_normalized("NFC", v["verbatim_txt"])
    assert v["readable_md"] == "Über die Käfer sind\n\n| Ort | Wesen |\n|---|---|\n| Köln | 2 |"
    assert v["readable_txt"] == "Über die Käfer sind\n\nOrt\tWesen\nKöln\t2"
    # a table never joins a paragraph across a page break
    t2 = Transcription(regions=[_region("a", "text", 0)], lines=[Line(id="x", region_id="a", reading_order=0, text="weiter")])
    assert T.variants([t, t2])["readable_txt"].endswith("Köln\t2\n\nweiter")


def test_item_text_writers(tmp_path: Path):
    pages = []
    for s, txt in ((1, "Die Unter-"), (2, "ſuchung.")):
        t = Transcription(regions=[_region("a", "text", 0)], lines=[Line(id="l", region_id="a", reading_order=0, text=txt)])
        pages.append(page_doc(f"b_{s}", "b", t, seq=s))
    docs = list(ItemTexts().run(iter(pages)))
    list(ItemTextWriter(str(tmp_path / "jsonl"), compression=None, output_filename="${variant}/${rank}.jsonl").run(
        ItemTextWriter(str(tmp_path / "files"), format="files").run(iter(docs))))
    assert (tmp_path / "files" / "verbatim_txt" / "b.txt").read_text() == "Die Unter-\fſuchung."
    assert (tmp_path / "files" / "readable_txt" / "b.txt").read_text() == "Die Untersuchung."
    assert (tmp_path / "files" / "readable_md" / "b.md").read_text() == "Die Untersuchung."
    with pytest.raises(ValueError):
        ItemTextWriter(str(tmp_path), format="csv")
    row = json.loads((tmp_path / "jsonl" / "readable_md" / "00000.jsonl").read_text())
    assert row["id"] == "b" and row["format"] == "text/markdown" and row["page_ids"] == ["b_1", "b_2"]
