"""NFC step and the item-level document (sections, dividers, paragraphs across page breaks)."""
from __future__ import annotations

import io
import unicodedata

import pytest
from PIL import Image

from linecaster.blocks.base.page import new_page_document, page_of, set_page
from linecaster.blocks.binding.item import BindItem
from linecaster.blocks.text.unicode import UnicodeNormalizer
from linecaster.blocks.writers.items import ItemExportsWriter
from linecaster.data.transcription import Line, Transcription, Word
from linecaster.formats.docling import DocumentBuilder, to_markdown, to_text
from linecaster.text.unicode import normalize_transcription

from conftest import page_t


# ---------------------------------------------------------------------- NFC
def test_normalize_unicode_nfc():
    dec = "Extremität"
    t = Transcription(lines=[Line(id="l0", text=dec, alternatives=[dec], bbox=[1, 2, 3, 4],
                                  words=[Word(id="w0", text=dec, bbox=[1, 2, 3, 4], alternatives=["ä"])])])
    assert normalize_transcription(t) == 4
    ln = t.lines[0]
    assert ln.text == "Extremität" == unicodedata.normalize("NFC", dec) and ln.alternatives == ["Extremität"]
    assert ln.words[0].text == "Extremität" and ln.words[0].alternatives == ["ä"] and ln.words[0].bbox == [1, 2, 3, 4]
    m = t.model[-1]
    assert (m.step, m.settings["form"], m.measurements["changed"]) == ("unicode", "NFC", 4)
    assert normalize_transcription(t) == 0                    # idempotent
    with pytest.raises(ValueError):
        normalize_transcription(t, "NFKC")                    # compatibility folding is refused


def test_normalize_unicode_block_updates_doc_text():
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, format="PNG")
    doc = new_page_document("p", buf.getvalue())
    page = page_of(doc)
    page.transcriptions["ocr"] = Transcription(lines=[Line(id="l0", text="schön")])
    set_page(doc, page)
    out = list(UnicodeNormalizer().run(iter([doc])))
    assert out[0].text == "schön" and page_of(out[0]).transcriptions["ocr"].lines[0].text == "schön"


# --------------------------------------------------------------- item level


def two_pages():
    return [page_t(1, ["It was a dark and stormy night when the", "ship left the harbour and turned to"], "CHAPTER I"),
            page_t(2, ["the north, where the ice waited.", "Nobody spoke."])]


def test_paragraph_continues_across_the_page_break_with_page_provenance():
    b = DocumentBuilder("book", text="reflow")
    for t in two_pages():
        b.add_page(t, 1000, 1000)
    doc = b.build()
    para = [x for x in doc.texts if x.text.startswith("It was")][0]
    assert "turned to the north, where the ice waited." in para.text
    assert sorted({p.page_no for p in para.prov}) == [1, 2]
    assert b.stats.continuations == 1 and sorted(doc.pages) == [1, 2]
    assert "1" not in to_text(doc).split("\n") and "1" in to_text(doc, furniture=True).split("\n")


def test_sections_and_dividers():
    b = DocumentBuilder("book", text="lines", sections=True)
    for t in two_pages():
        b.add_page(t, 1000, 1000)
    doc = b.build()
    assert len(doc.groups) == 1 and doc.groups[0].name == "CHAPTER I"
    assert all(c.cref in {x.self_ref for x in doc.texts} for c in doc.groups[0].children)
    assert len(doc.groups[0].children) == len(doc.texts)       # everything after the heading is in its section
    md = to_markdown(doc, region_of=b.region_of)
    assert md.split("\n\n---\n\n")[0] == "### CHAPTER I"
    assert md.count("---") == 2                                # heading | p1 text | p2 text (furniture left out)
    assert to_markdown(doc, furniture=True, region_of=b.region_of).count("---") == 4


def test_item_blocks_group_pages_and_write(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (1000, 1000)).save(buf, format="PNG")
    docs = []
    for seq, t in reversed(list(enumerate(two_pages(), start=1))):     # out of order on purpose
        d = new_page_document(f"b1-{seq}", buf.getvalue(), item_id="b1", sequence=seq)
        p = page_of(d)
        p.transcriptions["ocr"] = t
        p.metadata["item_page_count"] = 2
        set_page(d, p)
        docs.append(d)
    out = list(ItemExportsWriter(str(tmp_path), formats=("md", "txt", "json"), dividers=True).run(
        BindItem(text="reflow", sections=True).run(iter(docs))))
    assert len(out) == 1 and out[0].id == "b1" and out[0].metadata["page_ids"] == ["b1-1", "b1-2"]
    md = (tmp_path / "b1.md").read_text()
    assert md.startswith("### CHAPTER I") and "turned to the north" in md   # docling nests the heading one level in its section
    assert (tmp_path / "b1.txt").exists() and (tmp_path / "b1.json").exists()


def test_reflow_with_sections_and_a_title_keeps_a_consistent_tree():
    # squiddleocr 7c8a052 crashes here ("Document hierarchy is inconsistent"): its reflow path re-parents
    # the title into a new section without detaching it; here the section opens first, the title inside
    pages = two_pages()
    pages[0].regions[0].label = "title"
    b = DocumentBuilder("book", text="reflow", sections=True)
    for t in pages:
        b.add_page(t, 1000, 1000)
    doc = b.build()
    title = [x for x in doc.texts if x.label == "title"][0]
    assert title.parent.cref == doc.groups[0].self_ref and doc.groups[0].children[0].cref == title.self_ref
    assert to_markdown(doc).startswith("# CHAPTER I")
