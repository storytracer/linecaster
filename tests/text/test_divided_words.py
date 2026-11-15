"""The normalization ``divided-words``: a word the source marks as divided (each half a ``joined`` edit of its span,
the whole word its text: Wikisource's ``{{hws}}``/``{{hwe}}``, ALTO's ``SUBS_CONTENT``) written whole where the
second half stands, the first half left out; a compound's own hyphen kept. Without it the text stays as printed."""
from __future__ import annotations

import pytest

from linecaster.data import Annotator, Edit, Transcription
from linecaster.document import DocumentBuilder, to_text
from linecaster.document.strategy import apply


def page(*rows: str, halves: dict[int, tuple[str, str]] = {}) -> Transcription:
    """A page of one region, a line per row; ``halves``: row -> (the half as printed, the whole word), a joined
    edit of the half's span."""
    t = Transcription()
    a = t.add_annotator(Annotator(kind="human", step="transcription", name="proofreaders"))
    t.add_region(a, "r0", role="paragraph")
    for k, text in enumerate(rows):
        t.add_line(a, f"l{k}", region="r0", text=text)
        if k in halves:
            half, whole = halves[k]
            start = text.index(half)
            t.edits.append(Edit(annotator=a, target=f"l{k}[{start}:{start + len(half)}]", kind="joined", text=whole))
    t.add_order(a, ["r0"], [ln.id for ln in t.lines], list(range(len(rows))))
    return t


def item(*pages: Transcription):
    b = DocumentBuilder("item")
    for k, t in enumerate(pages):
        b.add_page(t, page_id=f"p{k}")
    return b.build()


@pytest.mark.parametrize("first, half1, second, half2, whole, joined", [
    ("The cicada's food de-", "de-", "pends upon it.", "pends", "depends", ["The cicada's food", "depends upon it."]),
    ("such inter-", "inter-", "crossing of races.", "crossing", "inter-crossing",
     ["such", "inter-crossing of races."]),
    ("the hills ﬂush-", "ﬂush-", "ed red.", "ed", "flushed", ["the hills", "flushed red."]),
])
def test_a_word_divided_across_pages(first, half1, second, half2, whole, joined):
    doc = item(page(first, halves={0: (half1, whole)}), page(second, halves={0: (half2, whole)}))
    assert [b.text for b in doc.blocks] == [first, second]                      # literal: as printed
    written = apply(doc, "divided-words")
    assert [b.text for b in written.blocks] == joined
    assert not any(s.edit == "joined" for b in written.blocks for s in b.spans)   # applied: the edits are gone


def test_a_word_divided_within_a_page_and_flowed():
    doc = item(page("giue thee the furthe-", "rance of knowledge",
                    halves={0: ("furthe-", "furtherance"), 1: ("rance", "furtherance")}))
    assert to_text(doc) == "giue thee the furthe-\nrance of knowledge"
    assert to_text(apply(doc, "divided-words")) == "giue thee the\nfurtherance of knowledge"


def test_a_half_without_its_partner_stays_as_printed():
    doc = item(page("the end of the de-", halves={0: ("de-", "depends")}), page("and something else."))
    assert [b.text for b in apply(doc, "divided-words").blocks] == ["the end of the de-", "and something else."]
