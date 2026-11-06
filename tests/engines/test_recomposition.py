"""The recomposition engine (``recomposition.unicode.v1``): every decision recorded with its reason, every threshold
an option, continuations across regions and pages (a page number between them keeps a paragraph open), and the
text-only fallback."""
import pytest

from conftest import line, page_with, region
from linecaster.data import Line, Region, Transcription
from linecaster.engines import UnicodeRecompositionEngine


def column(rid, rows, order=0, x=100, y=100, width=800, indents=(), short=(), gaps=(), label="text"):
    """A text region of ``rows`` 20 high every 30: rows in ``indents`` indented by 40, rows in ``short`` ending
    300 short of the margin, a blank row's height before the rows in ``gaps``."""
    lines, top = [], y
    for k, text in enumerate(rows):
        top += 30 if k in gaps else 0
        x0 = x + (40 if k in indents else 0)
        x1 = x + width - (300 if k in short else 0)
        lines.append(line(rid, k, x0, top, x1 - x0, 20, text))
        top += 30
    return region(rid, label, x, y, width, top - y, order), lines


def recompose(*regions_lines, **options):
    regions = [r for r, _ in regions_lines]
    lines = [ln for _, ls in regions_lines for ln in ls]
    (t,) = UnicodeRecompositionEngine(**options)([page_with(regions, lines)])
    return t


def decisions(p):
    return [(d.kind, d.reason, d.row) for d in p.decisions]


# --------------------------------------------------------------------------------------------- decisions

def test_division_marks_removed_and_kept_with_their_reasons():
    t = recompose(column("text_0", ["Die Untersuchung der Ab-", "lagerungen zeigt den Nord-", "Ostsee-", "Raum in",
                                    "den Jahren um-", "1914 und die Fluss-", "- und Bachläufe des Kanton-",
                                    "Bern mit der Nord-", "see und der Nord-See zu-", "sammen."]))
    (p,) = t.paragraphs
    assert decisions(p) == [("mark_removed", "letter_follows", 0), ("hyphen_kept", "capital_follows", 1),
                            ("hyphen_kept", "capital_follows", 2), ("hyphen_kept", "digit_follows", 4),
                            ("hyphen_kept", "no_letter_follows", 5), ("hyphen_kept", "capital_follows", 6),
                            ("hyphen_kept", "attested", 7), ("mark_removed", "letter_follows", 8)]
    assert p.text.startswith("Die Untersuchung der Ablagerungen zeigt den Nord-Ostsee-Raum in den Jahren um-1914")
    assert "der Nord-see und der Nord-See zusammen." in p.text          # the document has Nord-See, not Nordsee
    m = t.steps[-1].measurements
    assert (m["marks_removed"], m["marks_kept"], m["paragraphs"], m["continuations"]) == (2, 6, 1, 0)


def test_a_hebrew_mark_before_latin_is_a_script_change():
    t = recompose(column("text_0", ["שלו-", "teil und mehr"]))
    assert decisions(t.paragraphs[0]) == [("hyphen_kept", "script_change", 0)]


def test_paragraph_breaks_with_their_reasons():
    rows = ["A first paragraph runs on", "to the end of the column.", "An indented one starts here", "and ends.",
            "After a gap a third one", "runs to the end of the line", "and stops short.", "A fourth one starts flush."]
    t = recompose(column("text_0", rows, indents={2}, gaps={4}, short={6}))
    assert [p.text.split()[:2] for p in t.paragraphs] == [["A", "first"], ["An", "indented"], ["After", "a"],
                                                            ["A", "fourth"]]
    assert [decisions(p) for p in t.paragraphs] == [[], [("paragraph_break", "indent", 0)],
                                                    [("paragraph_break", "gap", 0)],
                                                    [("paragraph_break", "short_row", 0)]]


def test_a_paragraph_continues_into_the_next_region():
    a = column("text_0", ["The nest is built of dead", "grasses and bents, and the lin-"])
    b = column("text_1", ["ing of finer stuff.", "A new sentence."], order=1, y=400)
    t = recompose(a, b)
    first, second = t.paragraphs
    assert first.text == "The nest is built of dead grasses and bents, and the lin"      # the mark is gone
    assert first.rows[-1].end == len(first.text)
    assert decisions(first) == [("mark_removed", "letter_follows", 1), ("continuation", "division_mark", 1)]
    assert first.decisions[-1].separator == "" and second.text == "ing of finer stuff. A new sentence."
    assert first.continues.model_dump() == {"id": "text_1_p0", "page_id": None}
    assert second.continues_from.model_dump() == {"id": "text_0_p0", "page_id": None}
    m = t.steps[-1].measurements
    assert (m["paragraphs"], m["continuations"], m["marks_removed"]) == (1, 1, 1)
    # reaching the end margin without a mark: a space joins them
    t = recompose(column("text_0", ["The nest is built of dead", "grasses and bents, and the"]),
                  column("text_1", ["lining of finer stuff."], order=1, y=400))
    assert decisions(t.paragraphs[0]) == [("continuation", "end_margin", 1)]
    assert t.paragraphs[0].decisions[-1].separator == " "


def test_what_ends_the_running_text():
    """A sentence end, an indented first row, a heading or a picture between: no continuation."""
    a = ["The nest is built of dead", "grasses and bents, and the"]
    assert all(p.continues is None for p in recompose(column("text_0", [*a[:1], "grasses and bents."]),
                                                      column("text_1", ["lining"], order=1, y=400)).paragraphs)
    indented = column("text_1", ["lining of finer", "stuff."], order=1, y=400, indents={0})
    assert recompose(column("text_0", a), indented).paragraphs[0].continues is None
    for between in (column("title_1", ["A HEADING"], order=1, y=300, label="section_header"),
                    (region("picture_1", "picture", 100, 300, 800, 50, 1), [])):
        t = recompose(column("text_0", a), between, column("text_2", ["lining of finer stuff."], order=2, y=400))
        assert all(p.continues is None and p.continues_from is None for p in t.paragraphs)


# ---------------------------------------------------------------------------------------- across pages

def item(*pages):
    return UnicodeRecompositionEngine()(list(pages), page_ids=[f"b_{k:04d}" for k in range(1, len(pages) + 1)])


def page(rows, number=None, **kw):
    parts = [column("text_0", rows, **kw)]
    if number is not None:
        parts.append((region("number_1", "page_footer", 450, 900, 40, 20, 1, raw="number"),
                      [line("number_1", 0, 450, 900, 40, 20, number)]))
    return page_with([r for r, _ in parts], [ln for _, ls in parts for ln in ls])


def test_a_page_number_between_two_pages_does_not_close_the_paragraph():
    first = page(["It was a dark and stormy night when", "the ship left the harbour and turned to"], number="12")
    second = page(["the north, where the ice waited."], number="13")
    a, b = item(first, second)
    (end, number), (start, _) = a.paragraphs, b.paragraphs
    assert number.text == "12" and number.continues is None and number.continues_from is None
    assert end.continues.model_dump() == {"id": "text_0_p0", "page_id": "b_0002"}
    assert start.continues_from.model_dump() == {"id": "text_0_p0", "page_id": "b_0001"}
    assert (a.steps[-1].measurements["continuations"], b.steps[-1].measurements["continuations"]) == (0, 1)
    # a page number with a letter in it is text: it closes the paragraph
    a, b = item(page(first.lines[0].text.split("\n") + ["the ship left the harbour and turned to"], number="p. 12"),
                second)
    assert all(p.continues is None for p in a.paragraphs)
    # each page alone: no continuation across the break
    for t in (page(["It was a dark and stormy night when", "the ship left the harbour and turned to"], number="12"),):
        (alone,) = UnicodeRecompositionEngine()([t])
        assert all(p.continues is None for p in alone.paragraphs)


def test_a_continuation_over_three_pages_decides_on_the_whole_text():
    """The chain's text so far is what the next decision reads: the lexicon's lookup for the last word."""
    pages = [page(["The rows of the first page run", "on to the next one without a stop and the"]),
             page(["text goes on here and ends in Nord-"]),
             page(["see, where Nord-See is the other form."])]
    a, b, c = item(*pages)
    assert a.paragraphs[0].continues.page_id == "b_0002" and b.paragraphs[0].continues.page_id == "b_0003"
    assert decisions(b.paragraphs[0])[-2:] == [("hyphen_kept", "attested", 0), ("continuation", "division_mark", 0)]
    assert b.paragraphs[0].decisions[-1].separator == ""                 # attested: no space after the hyphen


# ------------------------------------------------------------------------------------------- thresholds

def test_every_recomposition_threshold_is_an_option():
    rows = ["A first paragraph runs on", "to the end of the column.", "An indented one starts here", "and ends.",
            "After a gap a third one", "runs to the end of the line", "and stops short.", "A fourth one starts flush."]
    c = column("text_0", rows, indents={2}, gaps={4}, short={6})
    count = lambda **o: len(recompose(c, **o).paragraphs)          # noqa: E731
    assert count() == 4
    assert count(indent=3.0) == 3                     # 40 px is 2 ems: not indented enough
    assert count(gap_leading=3.0) == 3                # the gap is no blank line
    assert count(gap_height=3.0) == 3
    assert count(short_row=20.0) == 3                 # 300 px is 15 ems: not short enough
    assert count(short_row_width=0.5) == 3
    assert count(justified_share=1.0) == 3            # not justified: a short row ends nothing
    assert count(justified_rows=20) == 3
    # a paragraph that reaches the end margin runs on; with a tighter margin it does not
    a, b = column("text_0", ["The nest is built of dead", "grasses and bents, and the"]), \
        column("text_1", ["lining of finer stuff."], order=1, y=400)
    assert recompose(a, b).paragraphs[0].continues is not None
    a2 = column("text_0", ["The nest is built of dead", "grasses and bents, and the"], short={1})
    assert recompose(a2, b).paragraphs[0].continues is None
    assert recompose(a2, b, end_margin=20.0).paragraphs[0].continues is not None
    # convention marks
    marks = column("text_0", ["Die Untersuchung der Ab¬", "lagerungen ist alt; die Ab=", "lagerungen"])
    assert recompose(marks).paragraphs[0].text == "Die Untersuchung der Ablagerungen ist alt; die Ab= lagerungen"
    assert recompose(marks, convention_marks="¬=").paragraphs[0].text == \
        "Die Untersuchung der Ablagerungen ist alt; die Ablagerungen"
    # right to left: the start margin is on the right
    rtl = page_with([region("text_0", "text", 100, 100, 800, 90, 0)],
                    [line("text_0", 0, 100, 100, 800, 20, "שורה ראשונה של הפסקה"),
                     line("text_0", 1, 100, 130, 760, 20, "פסקה חדשה מוזחת מימין"),
                     line("text_0", 2, 100, 160, 800, 20, "והיא ממשיכה")])
    assert len(UnicodeRecompositionEngine()([rtl.model_copy(deep=True)])[0].paragraphs) == 1
    assert len(UnicodeRecompositionEngine(rtl=True)([rtl.model_copy(deep=True)])[0].paragraphs) == 2
    with pytest.raises(ValueError):
        UnicodeRecompositionEngine(no_such=1)


# -------------------------------------------------------------------------------------------- text only

def test_text_only_transcriptions_make_one_paragraph_per_region():
    """Without geometry: a region (or a page without regions) is one paragraph, division marks by the Unicode
    rules and the lexicon, no geometric paragraph breaks; only a mark leaves it open."""
    lines = [Line(id=f"l{i}", reading_order=i, text=s) for i, s in
             enumerate(["Die Untersuchung der Ab-", "lagerungen zeigt den Nord-", "Ostsee-Raum.", "", "Ein Absatz."])]
    (t,) = UnicodeRecompositionEngine()([Transcription(lines=lines)])
    (p,) = t.paragraphs
    assert p.text == "Die Untersuchung der Ablagerungen zeigt den Nord-Ostsee-Raum. Ein Absatz."
    assert p.region_id is None and [r.lines for r in p.rows] == [["l0"], ["l1"], ["l2"], ["l4"]]
    assert decisions(p) == [("mark_removed", "letter_follows", 0), ("hyphen_kept", "capital_follows", 1)]
    # regions without geometry in their lines: one paragraph each, continued by a division mark only
    box = [[0, 0], [10, 0], [10, 10], [0, 10]]
    regions = [Region(id="r0", label="text", polygon=box, bbox=[0, 0, 10, 10], reading_order=0),
               Region(id="r1", label="text", polygon=box, bbox=[0, 0, 10, 10], reading_order=1)]
    lines = [Line(id="a", region_id="r0", text="Die Unter-"), Line(id="b", region_id="r1", text="suchung ist alt.")]
    (t,) = UnicodeRecompositionEngine()([Transcription(regions=regions, lines=lines)])
    first, second = t.paragraphs
    assert first.continues.id == "r1_p0" and first.text + second.text == "Die Untersuchung ist alt."
    from linecaster.formats.docling import build_docling

    doc = build_docling(t)
    assert [x.text for x in doc.texts] == ["Die Untersuchung ist alt."]
