"""The script samples (``linecaster.testing.scripts``) through everything that depends on a script or a direction:
what a page records and resolves, what a text says about itself, the tokenizers, the scorer, and the reading order
of regions and lines in each direction."""
from __future__ import annotations

import random

import pytest

from linecaster.blocks.lines.assigner import order_rows
from linecaster.data.geometry.order import xy_cut_order
from linecaster.scoring import score_page, tokens
from linecaster.testing.scripts import SCRIPT_SAMPLES, script_page
from linecaster.text.scripts import dominant_script, first_strong_direction
from linecaster.text.typography import zone_bbox

SAMPLES = sorted(SCRIPT_SAMPLES)
# the script ``dominant_script`` reads from a sample's characters (Fraktur is Latin to Unicode)
LETTERS = {"fraktur": "Latn"}
# words: whitespace, uax29
WORDS = {"latin": (14, 14), "fraktur": (13, 13), "greek": (16, 16), "cyrillic": (12, 12), "arabic": (11, 11),
         "hebrew": (9, 9), "devanagari": (8, 8), "thai": (4, 26), "chinese": (4, 16), "japanese": (3, 23),
         "korean": (7, 9), "mongolian": (7, 7)}


def test_twelve_samples_in_all_four_directions():
    assert len(SAMPLES) == 12
    assert {s.direction for s in SCRIPT_SAMPLES.values()} == {"horizontal-lr", "horizontal-rl", "vertical-rl",
                                                              "vertical-lr"}


@pytest.mark.parametrize("sid", SAMPLES)
def test_a_page_records_its_writing_system_and_every_line_resolves_it(sid):
    s, t = SCRIPT_SAMPLES[sid], script_page(sid)
    assert [t.text_of(ln) for ln in t.ordered_lines()] == s.lines
    for ln in t.lines:
        assert (t.language(ln.id), t.script(ln.id), t.direction(ln.id)) == (s.language, s.script, s.direction)


@pytest.mark.parametrize("sid", SAMPLES)
def test_a_sample_s_text_says_its_script_and_direction(sid):
    s = SCRIPT_SAMPLES[sid]
    text = " ".join(s.lines)
    assert dominant_script(text) == LETTERS.get(sid, s.script)
    assert first_strong_direction(text) == ("rtl" if s.direction == "horizontal-rl" else "ltr")


@pytest.mark.parametrize("sid", SAMPLES)
def test_words_by_each_tokenizer(sid):
    text = " ".join(SCRIPT_SAMPLES[sid].lines)
    assert (len(tokens(text)), len(tokens(text, "uax29"))) == WORDS[sid]
    # whitespace words are what lies between spaces, punctuation aside: no word falls apart at its marks
    assert all(w in text.split() or any(w in part for part in text.split()) for w in tokens(text))


@pytest.mark.parametrize("sid", SAMPLES)
@pytest.mark.parametrize("tokenizer", ["whitespace", "uax29", "characters"])
def test_a_page_scored_against_itself_is_perfect(sid, tokenizer):
    t = script_page(sid)
    for row in score_page(t, script_page(sid), tokenizer=tokenizer)["rows"]:
        assert row["s"] + row["d"] + row["i"] == 0 and row["words_both"] == row["words_true"] > 0


@pytest.mark.parametrize("sid", SAMPLES)
def test_regions_and_lines_are_ordered_in_the_page_s_direction(sid):
    t = script_page(sid)
    direction = t.direction("")
    regions = t.ordered_regions()
    shuffled = random.Random(7).sample(regions, len(regions))
    assert [shuffled[i].id for i in xy_cut_order([zone_bbox(r) for r in shuffled], direction=direction)] == [
        r.id for r in regions]
    for r in regions:
        lines = [ln for ln in t.ordered_lines() if ln.region == r.id]
        ordered, _rows = order_rows(random.Random(7).sample(lines, len(lines)), direction)
        assert [ln.id for ln in ordered] == [ln.id for ln in lines]
