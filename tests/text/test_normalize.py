"""Normalizations and strategies (catalog kinds, linecaster.text.normalize): each rule on hand-made cases, the lanes
rebuilt from normalizations giving the old lanes' output, latin-historic giving the old normalization table's."""
import random

import pytest

from linecaster.catalog.registry import catalog
from linecaster.errors import CatalogError
from linecaster.scoring import lanes
from linecaster.text.normalize import StructureRule, apply_rule

CASES = [
    "", "  The  ſtrange\tcaſe\n of  ﬁne ﬂour  ", "Straße ΣΊΣΥΦΟΣ ῆ", "क्षत्रिय नमस्ते", "ä ä é",
    "<b>bold</b> and <span class='x'>tags</span> <notatag> x<y", "# Heading\n- item\n* item\n---\n**strong** `code`",
    "<|im_start|> [[12, 34, 56, 78]] $x^2$ \\alpha \\frac{a}{b}", "illegible � word, soft­hyphen zero​width",
    "‘quotes’ “double” it`s ´acute ʼmodifier", "dash‐es: a‑b c‒d e–f g—h i―j", "ꝛ Ꝛ aͤ oͤ uͤ Aͤ Oͤ Uͤ eͤ",
    "full-width ＡＢＣ １２３ superscript ² ½", "de-\npends upon in-\n  ter-crossing", "Ⅻ ﬅ ﬆ ﬀ ﬃ ﬄ",
]
POOL = ("abcdefghijklmnopqrstuvwxyzABCXYZ0123456789 \t\n-–—‐‑‒―'’‘ʼ`´“”\"<>/|*~{}$\\#_=+[],.;:!?ſﬁﬂﬀﬃﬄﬅﬆꝛꞂßΣσςῆ"
        "̈́ͤ­​‌‍⁠﻿�äöüéñçøåæœÅÆŒक्षनमस्ते１２ＡＢ²½")


def corpus(n=300, seed=7):
    rnd = random.Random(seed)
    return CASES + ["".join(rnd.choice(POOL) for _ in range(rnd.randint(0, 60))) for _ in range(n)]


@pytest.mark.parametrize("strategy, old", [("diplomatic", lanes._diplomatic), ("alnum", lanes._alnum2),
                                           ("alnum-nonmark", lanes._alnum), ("ascii-alnum", lanes._ascii_alnum)])
def test_the_lanes_rebuilt_from_normalizations_are_the_old_lanes(strategy, old):
    s = catalog().strategy(strategy, use="comparison")
    for text in corpus():
        assert s.text(text) == old(text), repr(text)


def test_reading_is_the_old_lane_without_its_hyphen_join():
    s = catalog().strategy("reading", use="comparison")
    for text in corpus():
        if not any(c in text for c in "-‐‑‒–—―"):     # no hyphen to join
            assert s.text(text) == lanes._reading(text), repr(text)
    assert s.text("de-\npends") == "de- pends" and lanes._reading("de-\npends") == "depends"


def test_latin_historic_is_the_old_normalization_table():
    from linecaster.text.variants import normalize

    s = catalog().strategy("latin-historic", use="output")
    for text in corpus():
        assert s.text(text) == normalize(text), repr(text)


def test_each_rule():
    assert apply_rule("ä", {"unicode": "NFC"}) == "ä" and apply_rule("ﬁ", {"unicode": "NFKC"}) == "fi"
    assert apply_rule("aab", {"map": {"a": "x", "aa": "y"}}) == "yb"                     # the longest key first
    assert apply_rule("x­y", {"map": {"­": ""}}) == "xy"
    assert apply_rule("A b\nB", {"patterns": [{"match": "^b", "flags": ["M", "I"], "replace": "_"}]}) == "A b\n_"
    assert apply_rule("Straße", {"case": "fold"}) == "strasse" and apply_rule("Straße", {"case": "lower"}) == "straße"
    assert apply_rule("a-b�!c", {"keep": {"categories": ["L"], "ranges": [], "also": "�"}}) == "a b� c"
    assert apply_rule("a-b", {"keep": {"categories": [], "ranges": ["a-z"], "also": ""}}) == "a b"
    assert apply_rule("  a \n\t b ", {"whitespace": "collapse"}) == "a b"
    with pytest.raises(StructureRule):
        apply_rule("x", {"flow": True})


def test_strategies_literal_ad_hoc_and_their_uses():
    c = catalog()
    lit = c.strategy("literal")
    assert lit.literal and lit.text("  ſ  ") == "  ſ  " and lit.use == "output"
    ad = c.strategy("nfc+long-s")
    assert ad.id == "nfc+long-s" and ad.use == "output" and ad.text("ſ") == "s"
    assert c.strategy("long-s").text("ſ") == "s"                              # one normalization alone
    assert c.strategy("casefold+whitespace").use == "comparison"
    with pytest.raises(CatalogError, match="not for output"):
        c.strategy("casefold", use="output")                                   # comparison only
    with pytest.raises(CatalogError, match="is for comparison, not output"):
        c.strategy("alnum", use="output")
    with pytest.raises(CatalogError, match="unknown strategy"):
        c.strategy("no-such-thing")
    assert c.strategy("alnum").sha256 == c.dirs[0].read_index()["strategies"]["alnum"]
    assert c.strategy("reading").covers("ligatures") and not c.strategy("diplomatic").covers("long-s")


def test_a_language_specific_normalization_says_so():
    assert catalog().normalization("superscript-e").languages == ("de",)
    assert all(not catalog().normalization(n).languages for n in ("nfc", "nfkc", "long-s", "ligatures", "flow"))
