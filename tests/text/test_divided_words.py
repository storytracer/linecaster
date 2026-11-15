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


ALTO = """<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v4#"><Description><MeasurementUnit>pixel</MeasurementUnit>
</Description><Layout><Page ID="p1" WIDTH="1000" HEIGHT="1000" PHYSICAL_IMG_NR="1"><PrintSpace>
<TextBlock ID="b1" HPOS="100" VPOS="100" WIDTH="800" HEIGHT="60">
<TextLine ID="l1" HPOS="100" VPOS="100" WIDTH="800" HEIGHT="20">
<String ID="s1" CONTENT="The" HPOS="100" VPOS="100" WIDTH="60" HEIGHT="20"/><SP/>
<String ID="s2" CONTENT="cicada" HPOS="170" VPOS="100" WIDTH="100" HEIGHT="20"/><SP/>
<String ID="s3" CONTENT="de" SUBS_TYPE="HypPart1" SUBS_CONTENT="depends" HPOS="280" VPOS="100" WIDTH="40" HEIGHT="20"/>
<HYP CONTENT="-"/></TextLine>
<TextLine ID="l2" HPOS="100" VPOS="130" WIDTH="800" HEIGHT="20">
<String ID="s4" CONTENT="pends" SUBS_TYPE="HypPart2" SUBS_CONTENT="depends" HPOS="100" VPOS="130" WIDTH="80" HEIGHT="20"/>
<SP/><String ID="s5" CONTENT="upon" HPOS="190" VPOS="130" WIDTH="60" HEIGHT="20"/><SP/>
<String ID="s6" CONTENT="it." HPOS="260" VPOS="130" WIDTH="40" HEIGHT="20"/></TextLine>
</TextBlock></PrintSpace></Page></Layout></alto>"""


def test_alto_subs_content_is_the_sources_divided_word():
    """ALTO's ``SUBS_TYPE``/``SUBS_CONTENT`` (HypPart1, HypPart2) read as each half's joined edit, written back as
    they were; recomposed, ``divided-words+flow`` writes the word whole and ``flow`` alone keeps it as printed."""
    from linecaster.document import build_document
    from linecaster.engines import UnicodeRecompositionEngine
    from linecaster.formats import from_alto, to_alto

    t = from_alto(ALTO)
    assert [ln.reading.text for ln in t.lines] == ["The cicada de-", "pends upon it."]
    assert [(e.target, e.kind, e.text) for e in t.edits] == [("l1[11:14]", "joined", "depends"),
                                                              ("l2[0:5]", "joined", "depends")]
    written = to_alto(t).decode()
    assert 'SUBS_TYPE="HypPart1" SUBS_CONTENT="depends"' in written and 'SUBS_TYPE="HypPart2"' in written
    assert [(e.target, e.text) for e in from_alto(written).edits] == [(e.target, e.text) for e in t.edits]
    (r,) = UnicodeRecompositionEngine()([t])
    doc = build_document(r)
    assert to_text(apply(doc, "divided-words+flow")) == "The cicada depends upon it."
    assert to_text(apply(doc, "flow")) == "The cicada de-pends upon it."


def test_halves_pair_in_page_order_not_block_order():
    """A first half in a page's running foot (the editors' {{hws}} below the body) stands in a block that comes after
    the paragraph continuing onto the next page; the halves still pair, by the pages they stand on."""
    from linecaster.data import Link

    one = page("A word divided is the", halves={})
    a = one.annotators and 0
    one.add_region(a, "foot", role="page_footer")
    one.add_line(a, "f0", region="foot", text="sub-")
    one.edits.append(Edit(annotator=a, target="f0[0:4]", kind="joined", text="subject"))
    one.orders[-1].regions.append("foot")
    one.orders[-1].lines.append("f0")
    one.orders[-1].rows.append(0)
    two = page("ject of this note.", halves={0: ("ject", "subject")})
    one.links.append(Link(annotator=a, kind="runs_into", source="r0", target="p1#r0"))
    two.links.append(Link(annotator=a, kind="continues", source="r0", target="p0#r0"))
    doc = item(one, two)
    assert [b.kind for b in doc.blocks] == ["paragraph", "page_footer"]          # the foot after the paragraph
    written = apply(doc, "divided-words+flow")
    assert written.blocks[0].text == "A word divided is the subject of this note."
    assert written.blocks[1].text == ""
