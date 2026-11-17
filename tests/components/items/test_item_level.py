"""The literal text and NFC as a normalization; the item-level document (sections, dividers, paragraphs across page\nbreaks)."""
from __future__ import annotations

import io
import unicodedata

from PIL import Image

from linecaster.core.page import new_page_document, page_of, set_page
from linecaster.components.items import ItemAssembler
from linecaster.components.document import DocumentComposer
from linecaster.components.paragraphs import ParagraphBuilder
from linecaster.components.writers.items import ItemDocumentWriter
from linecaster.data.transcription import Annotator, Transcription, Word
from linecaster.engines import UnicodeParagraphsEngine
from linecaster.document import DocumentBuilder, to_markdown, to_text

from conftest import page_t


# ------------------------------------------------------- literal and NFC
def _read(text, words=()):
    t = Transcription()
    a = t.add_annotator(Annotator(step="recognition", name="test"))
    t.add_line(a, "l0", [1, 2, 3, 4])
    t.read(a, "l0", text, words=words, alternatives=[text])
    return t


def test_the_literal_text_is_the_reading_and_nfc_a_normalization():
    """A recognizer's decomposed text (kraken writes a + U+0308) is the literal text as read: nothing composes it
    unless a strategy names the normalization nfc."""
    from linecaster.document import build_document
    from linecaster.document.strategy import apply

    dec = "Extremita\u0308t"
    t = _read(dec, [Word(text=dec, box=[1, 2, 3, 4], alternatives=["a\u0308"])])
    assert t.text_of(t.lines[0]) == dec == t.text and not t.edits
    t = page_t(1, [dec, "und"])
    doc = build_document(t)
    assert to_text(doc).startswith(dec + "\nund")
    assert to_text(apply(doc, "nfc")).startswith("Extremität\nund") and "Extremität" == unicodedata.normalize("NFC", dec)
    assert apply(doc, "nfc").strategy == "nfc" and doc.strategy == "literal"


# --------------------------------------------------------------- item level


def two_pages():
    return [page_t(1, ["It was a dark and stormy night when the", "ship left the harbour and turned to"], "CHAPTER I"),
            page_t(2, ["the north, where the ice waited.", "Nobody spoke."])]


def recomposed_item(pages, ids=("b1-1", "b1-2")):
    """The pages recomposed as one item (``paragraphs.unicode.v1``), with their page ids."""
    return UnicodeParagraphsEngine()(pages, page_ids=list(ids))


def test_paragraph_continues_across_the_page_break_with_page_provenance():
    pages = recomposed_item(two_pages())
    b = DocumentBuilder("book")
    for t, pid in zip(pages, ("b1-1", "b1-2")):
        b.add_page(t, 1000, 1000, page_id=pid)
    doc = b.build()
    para = [x for x in doc.blocks if x.text.startswith("It was")][0]
    assert "turned to\nthe north, where the ice waited." in para.text                 # literal: rows as laid out
    from linecaster.document.strategy import apply

    flowed = [x for x in apply(doc, "flow").blocks if x.text.startswith("It was")][0]
    assert "turned to the north, where the ice waited." in flowed.text
    assert sorted({o.page for o in para.origins}) == [1, 2]
    assert [t.annotators[-1].measurements["continuations"] for t in pages] == [0, 1]
    assert [p.page for p in doc.pages] == [1, 2]
    first, second = (next(p for p in t.paragraphs if p.region == "text_1") for t in pages)   # the page number
    assert [d.kind for d in first.decisions] == ["continuation"]                          # between them stays apart
    assert pages[0].link(first.id, "runs_into") == f"b1-2#{second.id}"
    assert pages[1].link(second.id, "continues") == f"b1-1#{first.id}"
    assert "1" not in to_text(doc).split("\n") and "1" in to_text(doc, furniture=True).split("\n")


def test_sections_and_dividers():
    b = DocumentBuilder("book", sections=True)
    for t in two_pages():
        b.add_page(t, 1000, 1000)
    doc = b.build()
    heading = doc.blocks[0]
    assert (heading.kind, heading.text, heading.section) == ("heading", "CHAPTER I", heading.id)
    assert all(x.section == heading.id for x in doc.blocks)   # everything after the heading is in its section
    md = to_markdown(doc, dividers=True)
    assert md.split("\n\n---\n\n")[0] == "### CHAPTER I"
    assert md.count("---") == 2                                # heading | p1 text | p2 text (furniture left out)
    assert to_markdown(doc, furniture=True, dividers=True).count("---") == 4


def test_item_blocks_group_pages_and_write(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (1000, 1000)).save(buf, format="PNG")
    docs = []
    for seq, t in reversed(list(enumerate(two_pages(), start=1))):     # out of order on purpose
        d = new_page_document(f"b1-{seq}", buf.getvalue(), item_id="b1", sequence=seq)
        p = page_of(d)
        p.transcriptions["ocr_new"] = t
        p.metadata["item_page_count"] = 2
        set_page(d, p)
        docs.append(d)
    stream = iter(docs)
    for block in (ItemAssembler(), ParagraphBuilder("unicode-paragraphs", unit="item"),
                  DocumentComposer("linked-document", unit="item", options={"sections": True}),
                  ItemDocumentWriter(str(tmp_path), texts=("literal:md", "literal:txt", "literal:json", "flow:md"),
                                     dividers=True)):
        stream = block.run(stream)
    out = list(stream)
    assert len(out) == 1 and out[0].id == "b1"
    assert [p["page_id"] for p in out[0].metadata["item"]["pages"]] == ["b1-1", "b1-2"]
    md = (tmp_path / "literal" / "b1.md").read_text()
    assert md.startswith("### CHAPTER I") and "turned to\nthe north" in md   # a level-2 heading; rows as laid out
    assert "turned to the north" in (tmp_path / "flow" / "b1.md").read_text()
    assert (tmp_path / "literal" / "b1.txt").exists() and (tmp_path / "literal" / "b1.json").exists()


def test_a_title_opens_its_section_after_a_reflow():
    pages = two_pages()
    pages[0].classify(0, pages[0].regions[0].id, "role", "title")              # the layout called it a title
    b = DocumentBuilder("book", sections=True)
    for t, pid in zip(recomposed_item(pages), ("b1-1", "b1-2")):
        b.add_page(t, 1000, 1000, page_id=pid)
    doc = b.build()
    title = doc.blocks[0]
    assert title.kind == "title" and all(x.section == title.id for x in doc.blocks)
    assert to_markdown(doc).startswith("# CHAPTER I")
