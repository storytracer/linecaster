"""NFC step and the item-level document (sections, dividers, paragraphs across page breaks)."""
from __future__ import annotations

import io
import unicodedata

import pytest
from PIL import Image

from linecaster.blocks.base.page import new_page_document, page_of, set_page
from linecaster.blocks.binding import Binder
from linecaster.blocks.composition import Composer, Recomposer
from linecaster.blocks.text.unicode import UnicodeNormalizer
from linecaster.blocks.writers.items import ItemDocumentWriter
from linecaster.data.transcription import Annotator, Transcription, Word
from linecaster.engines import UnicodeRecompositionEngine
from linecaster.document import DocumentBuilder, to_markdown, to_text
from linecaster.text.unicode import normalize_transcription

from conftest import page_t


# ---------------------------------------------------------------------- NFC
def _read(text, words=()):
    t = Transcription()
    a = t.add_annotator(Annotator(step="recognition", name="test"))
    t.add_line(a, "l0", [1, 2, 3, 4])
    t.read(a, "l0", text, words=words, alternatives=[text])
    return t


def test_normalize_unicode_nfc():
    dec = "Extremita\u0308t"
    t = _read(dec, [Word(text=dec, box=[1, 2, 3, 4], alternatives=["a\u0308"]), Word(text="und", box=[5, 2, 3, 4])])
    assert normalize_transcription(t) == 2
    ln = t.lines[0]
    assert t.text_of(ln) == "Extremität" == unicodedata.normalize("NFC", dec)
    assert ln.reading.text == dec and ln.reading.alternatives == [dec]           # the reading stays as read
    assert [(e.target, e.kind, e.text) for e in t.edits] == [("l0", "nfc", "Extremität"), ("l0/0", "nfc", "Extremität")]
    assert ln.reading.words[0].box == [1, 2, 3, 4] and t.text == "Extremität"
    m = t.annotators[-1]
    assert (m.kind, m.step, m.settings["form"], m.measurements["changed"]) == ("rule", "unicode", "NFC", 2)
    assert all(e.annotator == 1 for e in t.edits)
    assert normalize_transcription(_read("Extremität")) == 0                  # NFC already: no edit
    with pytest.raises(ValueError):
        normalize_transcription(t, "NFKC")                    # compatibility folding is refused


def test_normalize_unicode_block_updates_doc_text():
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, format="PNG")
    doc = new_page_document("p", buf.getvalue())
    page = page_of(doc)
    page.transcriptions["ocr_new"] = _read("scho\u0308n")
    set_page(doc, page)
    out = list(UnicodeNormalizer().run(iter([doc])))
    t = page_of(out[0]).transcriptions["ocr_new"]
    assert out[0].text == "schön" and t.text_of(t.lines[0]) == "schön" and t.lines[0].reading.text == "scho\u0308n"


# --------------------------------------------------------------- item level


def two_pages():
    return [page_t(1, ["It was a dark and stormy night when the", "ship left the harbour and turned to"], "CHAPTER I"),
            page_t(2, ["the north, where the ice waited.", "Nobody spoke."])]


def recomposed_item(pages, ids=("b1-1", "b1-2")):
    """The pages recomposed as one item (``recomposition.unicode.v1``), with their page ids."""
    return UnicodeRecompositionEngine()(pages, page_ids=list(ids))


def test_paragraph_continues_across_the_page_break_with_page_provenance():
    pages = recomposed_item(two_pages())
    b = DocumentBuilder("book")
    for t, pid in zip(pages, ("b1-1", "b1-2")):
        b.add_page(t, 1000, 1000, page_id=pid)
    doc = b.build()
    para = [x for x in doc.blocks if x.text.startswith("It was")][0]
    assert "turned to the north, where the ice waited." in para.text
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
    for block in (Binder(), Recomposer("unicode-recomposition", unit="item"),
                  Composer("linked-composition", unit="item", options={"sections": True}),
                  ItemDocumentWriter(str(tmp_path), formats=("md", "txt", "json"), dividers=True)):
        stream = block.run(stream)
    out = list(stream)
    assert len(out) == 1 and out[0].id == "b1"
    assert [p["page_id"] for p in out[0].metadata["item"]["pages"]] == ["b1-1", "b1-2"]
    md = (tmp_path / "b1.md").read_text()
    assert md.startswith("### CHAPTER I") and "turned to the north" in md   # a level-2 heading
    assert (tmp_path / "b1.txt").exists() and (tmp_path / "b1.json").exists()


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
