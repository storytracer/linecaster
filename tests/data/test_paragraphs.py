"""Paragraphs and their decisions in the data model: the vocabulary is enforced, JSON round-trips exactly, and a
paragraph's rows hold what a document's provenance needs (the rows' boxes and character spans: ``DocumentBuilder``
makes a document's provenance from them)."""
import pytest
from pydantic import ValidationError

from linecaster.data import (DECISIONS, Annotator, Decision, Edit, Link, Paragraph, ParagraphRow, Source,
                             Transcription)
from linecaster.data.geometry import BBox

LINES = [
    (0, 100.0, 100.0, 900.0, 130.0, "Die Untersuchung der Gesteine zeigt, dass die Ab-"),
    (1, 100.0, 140.0, 500.0, 170.0, "lagerungen älter sind"),
    (1, 510.0, 140.5, 900.0, 170.0, "als man bisher annahm."),
    (2, 100.0, 180.0, 900.0, 210.0, ""),                         # a row without text
    (3, 140.0, 220.0, 900.0, 250.0, "Ein neuer Absatz beginnt eingerückt und"),
    (4, 100.0, 260.0, 600.0, 290.0, "endet hier."),
]


def page() -> Transcription:
    t = Transcription(source=Source(image_width=1000, image_height=1000))
    a = t.add_annotator(Annotator(step="layout", name="test"))
    t.add_region(a, "text_0", [90.0, 90.0, 820.0, 210.0], [[90.0, 90.0], [910.0, 90.0], [910.0, 300.0], [90.0, 300.0]],
                 label="text", role="text")
    for i, (_, x0, y0, x1, y1, text) in enumerate(LINES):
        t.add_line(a, f"l{i}", [x0, y0, x1 - x0, y1 - y0], [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], region="text_0",
                   text=text)
    t.add_order(a, ["text_0"], [f"l{i}" for i in range(len(LINES))], [row for row, *_ in LINES])
    return t


def paragraphs_of(t: Transcription) -> list[Paragraph]:
    """Paragraphs as a recomposition makes them from ``linecaster.text.recomposition`` (the rows of a region with
    the lines on each row), by a recomposition annotator."""
    from linecaster.text.recomposition import Lexicon, reflow_rows, region_rows, row_lines

    a = t.add_annotator(Annotator(kind="rule", step="recomposition", name="test"))
    lines = t.lines_of("text_0")
    rows, on_row = region_rows(t, lines), row_lines(t, lines)
    lexicon = Lexicon()
    lexicon.add("\n".join(r.text for r in rows))
    return [Paragraph(annotator=a, id=f"text_0_p{n}", parts=["text_0"], text=p.text,
                      rows=[ParagraphRow(lines=on_row[s.row], charspan=[s.start, s.end]) for s in p.spans])
            for n, p in enumerate(reflow_rows(rows, lexicon=lexicon))]


def test_paragraph_rows_give_the_documents_provenance():
    from linecaster.formats.docling import build_docling
    from linecaster.text.typography import line_bbox

    t = page()
    t.ranges.extend(paragraphs_of(t))
    assert [p.text for p in t.paragraphs] == [
        "Die Untersuchung der Gesteine zeigt, dass die Ablagerungen älter sind als man bisher annahm.",
        "Ein neuer Absatz beginnt eingerückt und endet hier."]
    by_id = {ln.id: ln for ln in t.lines}

    def box(row: ParagraphRow) -> BBox:
        boxes = [line_bbox(by_id[i]) for i in row.lines]
        return BBox(min(b.x0 for b in boxes), min(b.y0 for b in boxes), max(b.x1 for b in boxes),
                    max(b.y1 for b in boxes))

    ours = [(p.text, [((b := box(r)).x0, b.y0, b.x1, b.y1, *r.charspan) for r in p.rows]) for p in t.paragraphs]
    doc = build_docling(t)
    theirs = [(it.text, [(pv.bbox.l, pv.bbox.t, pv.bbox.r, pv.bbox.b, *pv.charspan) for pv in it.prov])
              for it in doc.texts]
    assert ours == theirs
    assert t.paragraphs[0].rows[1].lines == ["l1", "l2"]               # a row of two lines, one box


def test_paragraphs_round_trip_and_default_empty():
    t = page()
    assert t.paragraphs == [] and t.edits == [] and t.links == []
    t.ranges.extend(paragraphs_of(t))
    first, second = t.paragraphs
    first.decisions = [Decision(kind="mark_removed", reason="letter_follows", row=0),
                       Decision(kind="continuation", reason="end_margin", row=1, separator=" ")]
    t.links.append(Link(annotator=1, kind="runs_into", source=first.id, target="b_0002#text_0_p0"))
    second.decisions = [Decision(kind="paragraph_break", reason="indent")]
    t.edits += [Edit(annotator=1, target=second.id, kind="normalized", text=second.text),
                Edit(annotator=1, target="l0", kind="normalized", text=t.lines[0].reading.text)]
    assert Transcription.model_validate_json(t.model_dump_json()) == t
    assert Transcription.model_validate(t.model_dump(mode="json", by_alias=True, exclude_defaults=True)) == t


@pytest.mark.parametrize("kind", sorted(DECISIONS))
def test_decisions_have_a_fixed_vocabulary(kind):
    for reason in DECISIONS[kind]:
        Decision(kind=kind, reason=reason)
    with pytest.raises(ValidationError):
        Decision(kind=kind, reason="because")
    with pytest.raises(ValidationError):
        Decision(kind="guess", reason=DECISIONS[kind][0])
