"""The scorer: lanes on fixed strings, edit counts with the U+FFFD convention, the texts rendered under a policy,
role words and box-matched confusion, corpus rates and their bootstrap."""
from __future__ import annotations

import pytest

pytest.importorskip("rapidfuzz")

from linecaster.data import Annotator, Source, Transcription  # noqa: E402
from linecaster.scoring import (confusion, edit_counts, normalize, rates, role_rates, score_page,  # noqa: E402
                                text, words)


@pytest.mark.parametrize("lane,raw,want", [
    ("diplomatic@1", "  The  ſhip\n of\tSteers ", "The ſhip of Steers"),
    ("diplomatic", "Café", "Café"),
    ("reading@1", "The \u2018ſhip\u2019 \u2014 co-\noperative\u00ad", "the 'ship' - cooperative"),
    ("reading@1", "\u201cquoted\u201d \u2212 1", '"quoted" \u2212 1'),
    ("reading@1", "## A *b* <b>c</b> $x$ <Hand>", "a b c x <hand>"),
    ("reading@1", "ﬁne", "fine"),
    ("alnum@1", "Hello, World! 3rd—ed.", "hello world 3rd ed"),
    ("alnum@1", "a\ufffdc!", "a\ufffdc"),
    ("ascii-alnum@1", "The <b>Café</b>, 3rd—ſhip", "the caf 3rd hip"),
])
def test_lanes(lane, raw, want):
    assert normalize(raw, lane) == want


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


def test_score_page_counts_each_text_and_lane_and_the_roles():
    truth = _page([("header", "THE HISTORY"), ("paragraph", "The ship sailed."), ("page_number", "12")])
    out = _page([("paragraph", "THE HISTORY"), ("paragraph", "The shjp sailed."), ("footer", "12")])
    got = score_page(truth, out, lanes=("diplomatic@1", "alnum@1"))
    rows = {(r["text"], r["lane"]): r for r in got["rows"]}
    assert rows[("full", "diplomatic@1")]["s"] == 1
    assert rows[("body", "diplomatic@1")]["i"] == len("THE HISTORY\n")      # its head read as body text
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


def test_words_drop_punctuation_case_and_illegible_words():
    assert words("The ship, the SHIP; sh�p.") == {"the": 2, "ship": 2}


def test_corpus_rates_pool_the_counts_and_the_bootstrap_is_deterministic():
    recs = [{"page_id": f"p{k}", "item_id": f"i{k % 3}", "s": k % 2, "d": 0, "i": 0, "h": 9, "n": 10,
             "words_true": 4, "words_output": 4, "words_both": 3} for k in range(30)]
    a = rates(recs, "cer", seed=0, resamples=200)
    assert a["value"] == pytest.approx(15 / 300) and a["n"] == 30
    assert a == rates(recs, "cer", seed=0, resamples=200) and a["lo"] <= a["value"] <= a["hi"]
    assert rates(recs, "token_recall", resamples=0) == {"value": 0.75, "n": 30}
    assert role_rates([{"header": {"true": 2, "output": 4, "both": 2}}]) == {"header": {"precision": 0.5,
                                                                                         "recall": 1.0}}
