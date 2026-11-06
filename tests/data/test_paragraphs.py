"""Paragraphs and their decisions in the data model: the vocabulary is enforced, JSON round-trips exactly, and a
paragraph's rows hold what a document's provenance needs (the rows' boxes and character spans: ``DocumentBuilder``
makes a document's provenance from them)."""
import pytest
from pydantic import ValidationError

from linecaster.data import DECISIONS, Decision, Line, Paragraph, ParagraphRef, ParagraphRow, Region, Transcription
from linecaster.data.geometry import BBox


def _line(i, row, x0, y0, x1, y1, text):
    return Line(id=f"l{i}", region_id="text_0", reading_order=i, row=row, bbox=[x0, y0, x1 - x0, y1 - y0],
                polygon=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]], text=text)


def page() -> Transcription:
    lines = [
        _line(0, 0, 100.0, 100.0, 900.0, 130.0, "Die Untersuchung der Gesteine zeigt, dass die Ab-"),
        _line(1, 1, 100.0, 140.0, 500.0, 170.0, "lagerungen älter sind"),
        _line(2, 1, 510.0, 140.5, 900.0, 170.0, "als man bisher annahm."),
        _line(3, 2, 100.0, 180.0, 900.0, 210.0, ""),                         # a row without text
        _line(4, 3, 140.0, 220.0, 900.0, 250.0, "Ein neuer Absatz beginnt eingerückt und"),
        _line(5, 4, 100.0, 260.0, 600.0, 290.0, "endet hier."),
    ]
    region = Region(id="text_0", label="text", polygon=[[90.0, 90.0], [910.0, 90.0], [910.0, 300.0], [90.0, 300.0]],
                    bbox=[90.0, 90.0, 820.0, 210.0], reading_order=0)
    t = Transcription(regions=[region], lines=lines)
    t.source.image_width, t.source.image_height = 1000, 1000
    return t


def paragraphs_of(t: Transcription) -> list[Paragraph]:
    """Paragraphs as a recomposition makes them from ``linecaster.text.recomposition`` (the rows of a region with
    the lines on each row)."""
    from linecaster.formats.docling import region_rows
    from linecaster.text.recomposition import Lexicon, reflow_rows

    lines = t.lines_of("text_0")
    rows = region_rows(lines)
    on_row = [[ln.id for ln in lines if ln.row == k] for k in sorted({ln.row for ln in lines})]
    lexicon = Lexicon()
    lexicon.add("\n".join(r.text for r in rows))
    return [Paragraph(id=f"text_0_p{n}", region_id="text_0", text=p.text,
                      rows=[ParagraphRow(lines=on_row[s.row], start=s.start, end=s.end) for s in p.spans])
            for n, p in enumerate(reflow_rows(rows, lexicon=lexicon))]


def test_paragraph_rows_give_the_documents_provenance():
    from linecaster.formats.docling import build_docling
    from linecaster.text.typography import line_bbox

    t = page()
    t.paragraphs = paragraphs_of(t)
    assert [p.text for p in t.paragraphs] == [
        "Die Untersuchung der Gesteine zeigt, dass die Ablagerungen älter sind als man bisher annahm.",
        "Ein neuer Absatz beginnt eingerückt und endet hier."]
    by_id = {ln.id: ln for ln in t.lines}

    def box(row: ParagraphRow) -> BBox:
        boxes = [line_bbox(by_id[i]) for i in row.lines]
        return BBox(min(b.x0 for b in boxes), min(b.y0 for b in boxes), max(b.x1 for b in boxes),
                    max(b.y1 for b in boxes))

    ours = [(p.text, [((b := box(r)).x0, b.y0, b.x1, b.y1, r.start, r.end) for r in p.rows]) for p in t.paragraphs]
    doc = build_docling(t)
    theirs = [(it.text, [(pv.bbox.l, pv.bbox.t, pv.bbox.r, pv.bbox.b, *pv.charspan) for pv in it.prov])
              for it in doc.texts]
    assert ours == theirs
    assert t.paragraphs[0].rows[1].lines == ["l1", "l2"]               # a row of two lines, one box


def test_paragraphs_round_trip_and_default_empty():
    t = page()
    assert t.paragraphs == [] and all(ln.normalized is None for ln in t.lines)
    t.paragraphs = paragraphs_of(t)
    first, second = t.paragraphs
    first.decisions = [Decision(kind="mark_removed", reason="letter_follows", row=0),
                       Decision(kind="continuation", reason="end_margin", row=1, separator=" ")]
    first.continues = ParagraphRef(id="text_0_p0", page_id="b_0002")
    second.decisions = [Decision(kind="paragraph_break", reason="indent")]
    second.normalized = second.text
    t.lines[0].normalized = t.lines[0].text
    assert Transcription.model_validate_json(t.model_dump_json()) == t


@pytest.mark.parametrize("kind", sorted(DECISIONS))
def test_decisions_have_a_fixed_vocabulary(kind):
    for reason in DECISIONS[kind]:
        Decision(kind=kind, reason=reason)
    with pytest.raises(ValidationError):
        Decision(kind=kind, reason="because")
    with pytest.raises(ValidationError):
        Decision(kind="guess", reason=DECISIONS[kind][0])
