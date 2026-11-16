"""The scorer: lanes on fixed strings, edit counts with the U+FFFD convention, the texts rendered under a policy,
role words and box-matched confusion, corpus rates and their bootstrap."""
from __future__ import annotations

import pytest

pytest.importorskip("rapidfuzz")

from linecaster.data import Annotator, Source, Transcription  # noqa: E402
from linecaster.scoring import (confusion, edit_counts, normalize, rates, role_rates, score_page,  # noqa: E402
                                text, words)


@pytest.mark.parametrize("lane,raw,want", [
    ("diplomatic", "  The  ſhip\n of\tSteers ", "The ſhip of Steers"),
    ("diplomatic", "Café", "Café"),
    ("reading", "The \u2018ſhip\u2019 \u2014 co-\noperative\u00ad", "the 'ship' - co- operative"),
    ("reading", "\u201cquoted\u201d \u2212 1", '"quoted" \u2212 1'),
    ("reading", "## A *b* <b>c</b> $x$ <Hand>", "a b c x <hand>"),
    ("reading", "ﬁne", "fine"),
    ("alnum-nonmark", "Hello, World! 3rd—ed.", "hello world 3rd ed"),
    ("alnum-nonmark", "a\ufffdc!", "a\ufffdc"),
    ("ascii-alnum", "The <b>Café</b>, 3rd—ſhip", "the caf 3rd hip"),
    ("alnum", "The <b>Café</b>, 3rd—ſhip", "the café 3rd ship"),
    ("alnum", "\ufb01ne Stra\u00dfe", "fine strasse"),
    ("alnum", "cafe\u0301 na\u0131\u0308ve", "café naı\u0308ve"),
    ("alnum", "\u1f08\u03b8\u1fc6\u03bd\u03b1\u03b9, x\u00b2", "\u1f00\u03b8\u1fc6\u03bd\u03b1\u03b9 x2"),
    ("alnum", "\u0939\u093f\u0928\u094d\u0926\u0940 \u092d\u093e\u0937\u093e", "\u0939\u093f\u0928\u094d\u0926\u0940 \u092d\u093e\u0937\u093e"),
    ("alnum", "a\ufffdc! $\\frac{a}{b}$ <br/>x", "a\ufffdc a b x"),
    ("alnum", "co\u00adop\u200bera", "coopera"),
    ("alnum", "x", "x"),
])
def test_lanes(lane, raw, want):
    assert normalize(raw, lane) == want


def test_alnum_nonmark_splits_words_at_combining_marks():
    assert normalize("\u0939\u093f\u0928\u094d\u0926\u0940", "alnum-nonmark") != "\u0939\u093f\u0928\u094d\u0926\u0940"


def test_the_default_lane_and_the_lane_names_from_before_0_10():
    """Lanes are comparison strategies of the catalog; a name from before 0.10 is the strategy that does the same,
    with a warning (reading@1 without its hyphen join: no dehyphenation by default)."""
    from linecaster.catalog.registry import EditionWarning
    from linecaster.scoring import DEFAULT_LANE, lane

    assert DEFAULT_LANE == "diplomatic" == lane("diplomatic")
    for old, new in (("alnum@2", "alnum"), ("alnum@1", "alnum-nonmark"), ("reading@1", "reading"),
                     ("diplomatic@1", "diplomatic"), ("ascii-alnum@1", "ascii-alnum")):
        with pytest.warns(EditionWarning, match=old):
            assert lane(old) == new


def test_a_character_is_a_grapheme_cluster_unless_the_unit_says_code_point():
    """OCR-D counts grapheme clusters: a letter with a combining mark is one character, one error."""
    from linecaster.scoring import edit_counts

    g, c = edit_counts("a\u0308bc", "abc"), edit_counts("a\u0308bc", "abc", unit="codepoint")
    assert (g.s, g.d, g.n) == (1, 0, 3) and (c.s, c.d, c.n) == (0, 1, 4)
    assert edit_counts("x\ufffd\u0301y", "xzy").errors == 0          # an illegible cluster counts nowhere


def test_an_unknown_lane_is_refused():
    with pytest.raises(KeyError):
        normalize("x", "nowhere")


def test_edit_counts():
    c = edit_counts("kitten", "sitting")
    assert (c.s, c.d, c.i, c.h, c.n) == (2, 0, 1, 4, 6) and c.cer == pytest.approx(3 / 6)
    assert edit_counts("abc", "") == edit_counts("abc", "") and edit_counts("abc", "").d == 3
    assert edit_counts("", "xy").i == 2 and edit_counts("", "").cer is None


def test_an_illegible_character_is_never_an_error_nor_counted():
    c = edit_counts("ab�d", "abxd")
    assert (c.s, c.d, c.i, c.h, c.n) == (0, 0, 0, 3, 3)
    assert edit_counts("ab�d", "abd").errors == 0        # deleted: free too
    assert edit_counts("ab�d", "abxyd").i == 1           # an extra character is still inserted


def _page(lines: list[tuple[str, str]], boxes: bool = True) -> Transcription:
    t = Transcription(source=Source(image_width=1000, image_height=1000))
    a = t.add_annotator(Annotator(step="layout", name="test"))
    for k, (role, s) in enumerate(lines):
        rid = f"r{k}"
        t.add_region(a, rid, [0, 100 * k, 1000, 90] if boxes else None, role=role)
        t.add_line(a, f"l{k}", region=rid, text=s)
    t.add_order(a, [r.id for r in t.regions], [ln.id for ln in t.lines])
    return t


def test_the_full_text_keeps_the_furniture_and_the_body_text_leaves_it_out():
    t = _page([("header", "THE HISTORY"), ("paragraph", "Body text."), ("page_number", "12")])
    assert text(t, "full") == "THE HISTORY\nBody text.\n12"
    assert text(t, "body") == "Body text."


def test_a_removed_region_is_in_no_text_and_illegible_spans_are_replaced():
    t = _page([("paragraph", "keep this"), ("paragraph", "drop this")])
    t.classify(0, "r1", "status", "removed")
    t.classify(0, "l0[5:7]", "status", "illegible")
    assert text(t, "full") == "keep \ufffd\ufffdis"


def test_a_formula_region_is_its_latex_in_reading_order_with_or_without_lines():
    """A layout's formula read by a formula model is ``$LaTeX$`` in place of what the line recogniser read; one
    without lines takes its place in the regions' order (before the next region's first line)."""
    from linecaster.data.transcription import Formula

    t = _page([("paragraph", "the equations"), ("formula", "F1 d . . . Fn"), ("paragraph", "where e denotes")])
    t.formulas.append(Formula(annotator=0, target="r1", latex="F_{1}dq_{1}+F_{n}dq_{n}"))
    t.add_region(0, "r3", [0, 250, 1000, 40], role="formula")              # no lines, before the last paragraph
    t.formulas.append(Formula(annotator=0, target="r3", latex=" p_{1}=\\frac{d\\epsilon}{dq} "))
    t.orders.clear()
    t.add_order(0, ["r0", "r1", "r3", "r2"], ["l0", "l1", "l2"])
    assert text(t, "full") == ("the equations\n$F_{1}dq_{1}+F_{n}dq_{n}$\n$p_{1}=\\frac{d\\epsilon}{dq}$\n"
                               "where e denotes")
    t.formulas.append(Formula(annotator=0, target="l0[4:9]", latex="x"))  # an inline formula: the line's own text
    assert text(t, "body").startswith("the equations\n")


def test_a_page_is_in_every_slice_its_ground_truth_meets():
    from linecaster.data.transcription import Cell, Formula, Table
    from linecaster.scoring.slices import page_slices

    t = _page([("paragraph", "Body text."), ("table", "x")])
    assert page_slices(t, text(t, "full")) == ["plain"]
    grid = [Cell(start_row=r, end_row=r + 1, start_col=c, end_col=c + 1, text=f"cell {r}{c}")
            for r in range(3) for c in range(2)]
    t.tables.append(Table(annotator=0, target="r1", num_rows=3, num_cols=2, cells=grid))
    assert page_slices(t, "short") == ["tables", "table-heavy"]
    assert page_slices(t, "x" * 1000) == ["tables"]                                  # cells under 30 % of the text
    t.formulas.append(Formula(annotator=0, target="l0[0:4]", latex="x"))
    assert page_slices(t, "x" * 1000) == ["tables", "formulas"]


def test_score_page_counts_each_text_and_lane_and_the_roles():
    truth = _page([("header", "THE HISTORY"), ("paragraph", "The ship sailed."), ("page_number", "12")])
    out = _page([("paragraph", "THE HISTORY"), ("paragraph", "The shjp sailed."), ("footer", "12")])
    got = score_page(truth, out, lanes=("diplomatic", "alnum-nonmark"))
    rows = {(r["text"], r["lane"]): r for r in got["rows"]}
    assert rows[("full", "diplomatic")]["s"] == 1 and rows[("full", "diplomatic")]["unit"] == "grapheme"
    assert rows[("body", "diplomatic")]["i"] == len("THE HISTORY\n")      # its head read as body text
    assert got["roles"]["header"] == {"true": 2, "output": 0, "both": 0}
    assert got["roles"]["paragraph"]["output"] == 5
    conf = {(c["role_true"], c["role_output"]): c["count"] for c in got["confusion"]}
    assert conf == {("header", "paragraph"): 1, ("paragraph", "paragraph"): 1, ("page_number", "footer"): 1}


def test_a_failed_page_counts_as_empty():
    truth = _page([("paragraph", "abc")])
    (full, body) = score_page(truth, None)["rows"]
    assert full["d"] == 3 and full["n"] == 3


def test_confusion_without_boxes_is_empty_and_unmatched_regions_count_against_none():
    assert confusion(_page([("paragraph", "a")], boxes=False), _page([("paragraph", "a")], boxes=False)) == []
    t = _page([("paragraph", "a")])
    assert confusion(t, Transcription()) == [{"role_true": "paragraph", "role_output": "none", "count": 1}]


def test_words_drop_punctuation_and_illegible_words_and_follow_the_lane():
    assert words("The ship, the SHIP; sh�p.", "alnum") == {"the": 2, "ship": 2}         # alnum folds case
    assert words("The ship, the SHIP; sh�p.") == {"The": 1, "ship": 1, "the": 1, "SHIP": 1}   # diplomatic keeps it


def test_corpus_rates_pool_the_counts_and_the_bootstrap_is_deterministic():
    recs = [{"page_id": f"p{k}", "item_id": f"i{k % 3}", "s": k % 2, "d": 0, "i": 0, "h": 9, "n": 10,
             "words_true": 4, "words_output": 4, "words_both": 3} for k in range(30)]
    a = rates(recs, "cer", seed=0, resamples=200)
    assert a["value"] == pytest.approx(15 / 300) and a["n"] == 30
    assert a == rates(recs, "cer", seed=0, resamples=200) and a["lo"] <= a["value"] <= a["hi"]
    assert rates(recs, "token_recall", resamples=0) == {"value": 0.75, "n": 30}
    assert role_rates([{"header": {"true": 2, "output": 4, "both": 2}}]) == {"header": {"precision": 0.5,
                                                                                         "recall": 1.0}}
