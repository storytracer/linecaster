"""Per-page files (PageFileWriter), item texts with tables and NFC, item text writers."""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest
from lxml import etree

from linecaster.blocks.base.page import page_of
from linecaster.blocks.binding import Binder
from linecaster.blocks.composition.composer import Composer
from linecaster.blocks.composition.recomposer import Recomposer
from linecaster.blocks.composition.typographer import Typographer
from linecaster.blocks.writers.files import PageFileWriter
from linecaster.blocks.text import CharacterNormalizer
from linecaster.blocks.writers.items import ItemTextWriter
from linecaster.data.transcription import Annotator, Transcription
from linecaster.errors import PipelineConfigError
from linecaster.formats import from_alto, from_hocr, from_page
from linecaster.formats.docling import DOCUMENT_KEY, EXPORT_FORMATS, compose, docling_dict, export, load_docling
from linecaster.text import variants as T

from conftest import item_variants, page_doc, page_with

SCHEMAS = Path(__file__).parents[2] / "schemas"


def test_page_files_all_formats_bucketed_and_valid(tmp_path: Path):
    docs = list(Composer("docling-composition@1").run(Typographer("ratios@1").run(iter([page_doc()]))))
    fmts = ("hocr", "alto", "page", "txt", "md", "json", "transcription")
    out = list(PageFileWriter(str(tmp_path), formats=fmts).run(iter(docs)))
    assert len(out) == 1
    folder = tmp_path / "book1"
    names = sorted(p.name for p in folder.iterdir())
    assert names == sorted(["p1.hocr", "p1.alto.xml", "p1.page.xml", "p1.txt", "p1.md", "p1.json",
                            "p1.transcription.json"])
    t = page_of(out[0]).transcriptions["ocr_new"]
    for name, reader in (("p1.hocr", from_hocr), ("p1.alto.xml", from_alto), ("p1.page.xml", from_page)):
        got = reader((folder / name).read_bytes())
        assert [got.text_of(ln) for ln in got.ordered_lines()] == [t.text_of(ln) for ln in t.ordered_lines()]
    for name, xsd in (("p1.alto.xml", "alto-4-4.xsd"), ("p1.page.xml", "pagecontent-2019-07-15.xsd")):
        schema = etree.XMLSchema(etree.parse(str(SCHEMAS / xsd)))
        assert schema.validate(etree.parse(str(folder / name))), schema.error_log
    assert (folder / "p1.md").read_text().startswith("# THE TITLE")
    assert json.loads((folder / "p1.json").read_text())["schema_name"] == "DoclingDocument"
    assert json.loads((folder / "p1.transcription.json").read_text())["regions"]


def test_page_files_flat_are_the_document_exports(tmp_path: Path):
    """Flat names with a suffix: each file is the document's export byte for byte, as the
    export writer this one replaces wrote them (flat, suffix, furniture)."""
    docs = list(Composer("docling-composition@1").run(Typographer("ratios@1").run(iter([page_doc()]))))
    list(PageFileWriter(str(tmp_path), formats=("md", "txt", "json"), suffix=".x", furniture=True,
                        bucket_by_item=False).run(iter(docs)))
    data = docs[0].metadata[DOCUMENT_KEY]                 # the Composer's document
    for fmt in ("md", "txt", "json"):
        expected = export(data if fmt == "json" else load_docling(data), fmt, True).encode("utf-8")
        assert (tmp_path / f"p1.x.{EXPORT_FORMATS[fmt]}").read_bytes() == expected, fmt
    assert sorted(p.name for p in tmp_path.iterdir()) == ["p1.x.json", "p1.x.md", "p1.x.txt"]


def lines_only(text: str = "nur Zeilen") -> Transcription:
    """A page of one read line and no region: it has no document."""
    t = Transcription()
    a = t.add_annotator(Annotator(step="lines", name="test"))
    t.add_line(a, "l0", [10, 10, 100, 20], text=text)
    t.add_order(a, lines=["l0"])
    return t


def test_page_files_without_composer_render_the_document(tmp_path: Path):
    """A page no ``Composer`` composed (e.g. read from page records) gets the document it would have composed."""
    docs = list(Typographer("ratios@1").run(iter([page_doc()])))
    assert DOCUMENT_KEY not in docs[0].metadata
    list(PageFileWriter(str(tmp_path / "w"), formats=("md", "json"), bucket_by_item=False).run(iter(docs)))
    page = page_of(docs[0])
    document, _ = compose(page.transcriptions["ocr_new"], name="p1", width=1000, height=1000)
    assert (tmp_path / "w" / "p1.json").read_text() == export(docling_dict(document), "json")
    assert (tmp_path / "w" / "p1.md").read_text().startswith("# THE TITLE")
    composed = list(Composer("docling-composition@1").run(iter(docs)))
    list(PageFileWriter(str(tmp_path / "c"), formats=("md", "json"), bucket_by_item=False).run(iter(composed)))
    for name in ("p1.md", "p1.json"):
        assert (tmp_path / "c" / name).read_bytes() == (tmp_path / "w" / name).read_bytes()
    # a document composed from another transcription is not this one's
    composed[0].metadata["docling_transcription"] = "ocr_original"
    composed[0].metadata[DOCUMENT_KEY] = {"broken": True}
    list(PageFileWriter(str(tmp_path / "o"), formats=("json",), bucket_by_item=False).run(iter(composed)))
    assert (tmp_path / "o" / "p1.json").read_bytes() == (tmp_path / "w" / "p1.json").read_bytes()


def test_page_files_without_document_fall_back_to_page_text(tmp_path: Path):
    t = lines_only()
    out = list(PageFileWriter(str(tmp_path), formats=("txt", "md", "json")).run(iter([page_doc(t=t, item=None)])))
    assert (tmp_path / "p1.txt").read_text() == "nur Zeilen" and (tmp_path / "p1.md").exists()
    assert not (tmp_path / "p1.json").exists() and len(out) == 1
    with pytest.raises(PipelineConfigError):
        PageFileWriter(str(tmp_path), formats=("pdf",))


def test_page_files_without_text_fallback_write_only_documents(tmp_path: Path):
    """``text_fallback=False``: a page without a document gets no file of a document format (the export
    writer's behavior), and a page with one gets them all."""
    t = lines_only()
    fmts = ("md", "txt", "html", "doclang", "json")
    composed = list(Composer("docling-composition@1").run(
        Typographer("ratios@1").run(iter([page_doc(page_id="p2", item=None)]))))
    out = list(PageFileWriter(str(tmp_path), formats=fmts, bucket_by_item=False, text_fallback=False).run(
        iter([page_doc(t=t, item=None), *composed])))
    assert len(out) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(f"p2.{EXPORT_FORMATS[f]}" for f in fmts)


def test_page_files_skip_failed_pages_when_asked(tmp_path: Path):
    """``skip_failed``: a page an earlier block failed on gets no files and passes on with its errors; by default it
    is written like any page."""
    from linecaster.blocks.base.page import record_error

    t = lines_only()
    ok, bad = page_doc(page_id="ok", t=t, item=None), page_doc(page_id="bad", t=t, item=None)
    record_error(bad, {"block": "LineRecognizer", "type": "RuntimeError", "error": "boom"})
    writer = PageFileWriter(str(tmp_path / "skip"), formats=("txt", "hocr"), skip_failed=True)
    out = list(writer.run(iter([ok, bad])))
    assert [d.id for d in out] == ["ok", "bad"] and out[1].metadata["errors"][0]["error"] == "boom"
    assert sorted(p.name for p in (tmp_path / "skip").iterdir()) == ["ok.hocr", "ok.txt"]
    assert writer.stats["skipped_failed"].total == 1
    list(PageFileWriter(str(tmp_path / "all"), formats=("txt",)).run(iter([ok, bad])))
    assert sorted(p.name for p in (tmp_path / "all").iterdir()) == ["bad.txt", "ok.txt"]


def _region(rid, label, order, **kw):
    """A page/2-style region (``page_with`` upgrades it)."""
    return {"id": rid, "label": label, "raw_label": label, "polygon": [[0, 0], [1, 0], [1, 1]], "bbox": [0, 0, 1, 1],
            "reading_order": order, **kw}


def _line(lid, region, order, text):
    return {"id": lid, "region_id": region, "reading_order": order, "text": text}


def test_variants_render_tables_and_nfc_input():
    table = {"cells": [{"text": "Ort", "row": 0, "col": 0}, {"text": "Weſen", "row": 0, "col": 1},
                       {"text": "Koͤln", "row": 1, "col": 0}, {"text": "2", "row": 1, "col": 1}]}
    decomposed = unicodedata.normalize("NFD", "Über die Käfer")
    t = page_with(
        [_region("h", "page_header", 0), _region("a", "text", 1), _region("t", "table", 2, extra={"table": table})],
        [_line("h0", "h", 0, "KOPF"), _line("a0", "a", 1, decomposed + " ſind"), _line("t0", "t", 2, "Ort Weſen"),
         _line("t1", "t", 3, "Köln 2")])
    v = item_variants([t])
    assert v["verbatim_txt"] == "KOPF\nÜber die Käfer ſind\n| Ort | Weſen |\n|---|---|\n| Koͤln | 2 |"
    assert unicodedata.is_normalized("NFC", v["verbatim_txt"])
    assert v["readable_md"] == "Über die Käfer sind\n\n| Ort | Wesen |\n|---|---|\n| Köln | 2 |"
    assert v["readable_txt"] == "Über die Käfer sind\n\nOrt\tWesen\nKöln\t2"
    # a table never joins a paragraph across a page break
    t2 = page_with([_region("a", "text", 0)], [_line("x", "a", 0, "weiter")])
    assert item_variants([t, t2])["readable_txt"].endswith("Köln\t2\n\nweiter")


def test_item_text_writers(tmp_path: Path):
    pages = []
    for s, txt in ((1, "Die Unter-"), (2, "ſuchung.")):
        t = page_with([_region("a", "text", 0)], [_line("l", "a", 0, txt)])
        pages.append(page_doc(f"b_{s}", "b", t, seq=s))
    stream = iter(pages)
    for block in (Binder(), Recomposer("unicode-recomposition@1", unit="item"),
                  CharacterNormalizer("latin-historic@1", unit="item"),
                  ItemTextWriter(str(tmp_path / "files"), format="files"),
                  ItemTextWriter(str(tmp_path / "jsonl"), compression=None, output_filename="${variant}/${rank}.jsonl",
                                 token_counter=len)):
        stream = block.run(stream)
    (item,) = list(stream)
    assert item.id == "b" and "item" in item.metadata                 # the item record passes through
    assert (tmp_path / "files" / "verbatim_txt" / "b.txt").read_text() == "Die Unter-\fſuchung."
    assert (tmp_path / "files" / "readable_txt" / "b.txt").read_text() == "Die Untersuchung."
    assert (tmp_path / "files" / "readable_md" / "b.md").read_text() == "Die Untersuchung."
    with pytest.raises(PipelineConfigError):
        ItemTextWriter(str(tmp_path), format="csv")
    row = json.loads((tmp_path / "jsonl" / "readable_md" / "00000.jsonl").read_text())
    assert row["id"] == "b" and row["format"] == "text/markdown" and row["page_ids"] == ["b_1", "b_2"]
    assert row["text"] == "Die Untersuchung." and row["token_count"] == len(row["text"])
    assert row["fidelity"] == "normalized" and row["pages"] == 2
    verbatim = ItemTextWriter(str(tmp_path), variants=("verbatim_txt",)).contract()
    assert {str(p) for p in verbatim.reads} == {"ocr_new:lines"}
    assert {str(p) for p in ItemTextWriter(str(tmp_path)).contract().reads} == {
        "ocr_new:lines", "ocr_new:paragraphs", "ocr_new:normalized"}
    with pytest.raises(PipelineConfigError):
        ItemTextWriter(str(tmp_path), variants=("nope",))
