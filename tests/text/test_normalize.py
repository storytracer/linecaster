"""Normalizations and strategies (catalog kinds, linecaster.text.normalize): each rule on hand-made cases, the lanes
rebuilt from normalizations giving the old lanes' output, latin-historic giving the old normalization table's."""
import random

import pytest

from linecaster.catalog.registry import catalog
from linecaster.errors import CatalogError
from linecaster.text.latex import latex_text
from linecaster.text.normalize import StructureRule, apply_rule

# ---- the lanes as linecaster 0.9 computed them (frozen here: the reference the strategies must match) ----
import re  # noqa: E402
import unicodedata  # noqa: E402

REPLACEMENT = "�"
_WS = re.compile(r"\s+")
_INVISIBLE = {ord(c): None for c in "­​‌‍⁠﻿"}
_QUOTES = {ord(c): "'" for c in "'\u2019\u2018\u02bc`\u00b4"}
_QUOTES.update({ord(c): '"' for c in "\u201c\u201d"})
_HYPHENS = {ord(c): "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015"}
_DEHYPHENATE = re.compile(r"-\s*\n\s*")


def _diplomatic(t: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFC", t)).strip()


#: HTML tag names the reading lane removes (a fixed list: angle brackets around other words are text)
_HTML_TAGS = ("a|b|big|blockquote|br|caption|center|code|col|colgroup|div|em|figcaption|figure|font|h[1-6]|hr|i|img|"
              "li|mark|ol|p|pre|s|small|span|strike|strong|sub|sup|table|tbody|td|tfoot|th|thead|tr|tt|u|ul")
#: markup the reading lane removes, as a space: special tokens, box arrays, HTML tags, Markdown headings, bullets
#: and rules, LaTeX macros, and the marks of emphasis, tables and formulas
_MARKUP = [re.compile(r"<\|/?[A-Za-z0-9_]+\|>"), re.compile(r"\[\[\s*\d[\d,\s]*\]\]"),
           re.compile(rf"</?(?:{_HTML_TAGS})(?:\s[^>\n]{{0,80}})?\s*/?>", re.I),
           re.compile(r"^[ \t]*#{1,6}[ \t]+", re.M), re.compile(r"^[ \t]*[-*+][ \t]+", re.M),
           re.compile(r"^[ \t]*[-=_*]{3,}[ \t]*$", re.M), re.compile(r"\\[a-zA-Z]+\*?"),
           re.compile(r"[`*|~{}$\\]")]
#: the markup ``reading@1`` and ``alnum@2`` remove, public for callers that must keep positions (replace each
#: match by as many spaces, then normalize the pieces)
MARKUP = tuple(_MARKUP)


def _reading(t: str) -> str:
    for rx in _MARKUP:
        t = rx.sub(" ", t)
    t = unicodedata.normalize("NFKC", t).translate(_INVISIBLE).translate(_QUOTES).translate(_HYPHENS)
    return _WS.sub(" ", _DEHYPHENATE.sub("", t).casefold()).strip()


_TAG = re.compile(r"<[^>]+>")
_ASCII_WORD = re.compile(r"[a-z0-9\ufffd]+")


def _ascii_alnum(t: str) -> str:
    return " ".join(_ASCII_WORD.findall(_TAG.sub(" ", t).lower()))


def _alnum(t: str) -> str:
    t = unicodedata.normalize("NFC", t).casefold()
    kept = "".join(c if c == REPLACEMENT or unicodedata.category(c)[0] in "LN" else " " for c in t)
    return _WS.sub(" ", kept).strip()


def _alnum2(t: str) -> str:
    for rx in _MARKUP:
        t = rx.sub(" ", t)
    t = unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", t).translate(_INVISIBLE).casefold())
    kept = "".join(c if c == REPLACEMENT or unicodedata.category(c)[0] in "LMN" else " " for c in t)
    return _WS.sub(" ", kept).strip()




class lanes:  # noqa: N801 - the old module's names
    _diplomatic, _reading, _alnum, _alnum2, _ascii_alnum = (staticmethod(f) for f in (
        _diplomatic, _reading, _alnum, _alnum2, _ascii_alnum))

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
    """The old lanes, on every text without a formula (0.10.4 put ``latex-text`` first in ``reading`` and ``alnum``)."""
    s = catalog().strategy(strategy, use="comparison")
    for text in corpus():
        if latex_text(text) == text:
            assert s.text(text) == old(text), repr(text)


def test_reading_is_the_old_lane_without_its_hyphen_join():
    s = catalog().strategy("reading", use="comparison")
    for text in corpus():
        if not any(c in text for c in "-‐‑‒–—―") and latex_text(text) == text:     # no hyphen to join, no formula
            assert s.text(text) == lanes._reading(text), repr(text)
    assert s.text("de-\npends") == "de- pends" and lanes._reading("de-\npends") == "depends"


#: linecaster 0.9's normalization table (``linecaster.text.variants.normalize``, removed in 0.10), frozen
_OLD_MAP = str.maketrans({"ſ": "s", "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
                          "ꝛ": "r", "Ꝛ": "R"})
_OLD_UMLAUT = {"a": "ä", "o": "ö", "u": "ü", "A": "Ä", "O": "Ö", "U": "Ü"}


def _old_normalize(s: str) -> str:
    import re
    import unicodedata

    s = unicodedata.normalize("NFC", s)
    s = re.sub("([aouAOU])\u0364", lambda m: _OLD_UMLAUT[m.group(1)], s)
    return unicodedata.normalize("NFC", s.translate(_OLD_MAP))


def test_latin_historic_is_the_old_normalization_table():
    normalize = _old_normalize
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


@pytest.mark.parametrize("raw, want", [
    ("$\\frac{1}{2}$ inch", "1\u20442 inch"), ("$1\\frac{1}{2}$", "11\u20442"),
    ("a vein ($Cu_{2}$) which", "a vein (Cu2) which"), ("($ Cu_2 $)", "(Cu2)"),
    ("costs $5 or $10", "costs $5 or $10"), ("$n$ degrees", "$n$ degrees"),         # printed dollars; a bare letter
    ("writing $q_{1},\\ldots q_{n}$ for", "writing q1,\u2026qn for"),
    ("writing $ q_1, \\ldots q_n $ for", "writing q1,\u2026qn for"),
    ("${\\dot {q}}_{1}$", "q\u03071"), ("45$^{\\circ}$ N", "45\u00b0 N"), ("$\\alpha$", "\u03b1"),
    ("$$\np_1 = \\frac{d\\epsilon_p}{dq_1}, \\quad \\text{etc.},\n$$", "p1=d\u03b5p\u2044dq1, etc.,"),
    ("$\\sqrt[3]{x^2}$", "\u221ax2"), ("$\\unknownmacro{x}$", "\\unknownmacrox"),
])
def test_latex_text_is_what_a_formula_prints(raw, want):
    assert latex_text(raw) == want


def test_a_formula_and_the_same_text_typed_compare_equal_in_reading_and_alnum():
    for lane in ("reading", "alnum"):
        s = catalog().strategy(lane, use="comparison")
        for formula, typed in [("$\\frac{1}{2}$", "\u00bd"), ("$1\\frac{1}{4}$ inches", "1\u00bc inches"),
                               ("$x^{2}$", "x\u00b2"), ("$Cu_{2}$", "Cu\u2082"), ("$\\alpha$-rays", "\u03b1-rays")]:
            assert s.text(formula) == s.text(typed), (lane, formula)
    assert catalog().strategy("diplomatic", use="comparison").text("$\\frac{1}{2}$") == "$\\frac{1}{2}$"  # diplomatic: as written


# ---- normalizations for writing traditions other than Latin: fixed strings, what must change and what must not ----

def _n(nid: str, use: str):
    return catalog().strategy(nid, use=use).text


def test_arabic_tatweel():
    for use in ("output", "comparison"):
        assert _n("arabic-tatweel", use)("كتـــاب") == "كتاب"
    assert catalog().normalization("arabic-tatweel").use == ("output", "comparison")


def test_arabic_marks_removes_vocalization_and_keeps_the_hamza():
    marks = _n("arabic-marks", "comparison")
    assert marks("كَتَبَ") == "كتب" and marks("مُحَمَّدٌ") == "محمد" and marks("هٰذَا") == "هذا"
    assert marks("ذٰلِكَ ٱلْكِتَٰبُ لَا رَيْبَۛ فِيهِۛ") == "ذلك ٱلكتب لا ريب فيه"     # Quranic marks; alef wasla stays
    assert marks("ا\u0654 ا\u0655 ا\u0653") == "ا\u0654 ا\u0655 ا\u0653"  # hamza, madda stay
    assert marks("\u06DD\u06DE\u06E9\u06E5\u06E6") == "\u06DD\u06DE\u06E9\u06E5\u06E6"  # signs, small waw and yeh stay
    with pytest.raises(CatalogError, match="not for output"):
        catalog().strategy("arabic-marks", use="output")


def test_arabic_letters():
    letters = _n("arabic-letters", "comparison")
    assert letters("أحمد إسلام آمن ٱلله") == "احمد اسلام امن الله"
    assert letters("مستشفى مدرسة") == "مستشفي مدرسه"
    assert letters("كتاب ئ ؤ") == "كتاب ئ ؤ"                                          # other hamza seats stay
    assert catalog().normalization("arabic-letters").use == ("comparison",)


def test_persian_arabic_letters():
    fa = _n("persian-arabic-letters", "output")
    assert fa("كتاب علي") == "کتاب علی"                                              # Arabic kaf and yeh
    assert fa("کتاب علی") == "کتاب علی"                                              # already Persian: unchanged
    assert fa("موسى") == "موسى"                                                      # alef maksura stays
    assert catalog().normalization("persian-arabic-letters").languages == ("fa", "ur")


def test_hebrew_points():
    points = _n("hebrew-points", "comparison")
    assert points("בְּרֵאשִׁית בָּרָא אֱלֹהִים") == "בראשית ברא אלהים"
    assert points("וַיֹּ֥אמֶר אֱלֹהִ֖ים יְהִ֣י א֑וֹר") == "ויאמר אלהים יהי אור"         # cantillation too
    assert points("בֵּית־הַסֵּפֶר׀ אוֹר׃") == "בית־הספר׀ אור׃"                        # maqaf, paseq, sof pasuq stay
    assert points("\uFB2A\uFB31\uFB4B") == "שבו"                                # pointed presentation forms
    assert catalog().normalization("hebrew-points").use == ("comparison",)


def test_greek_monotonic():
    for use in ("output", "comparison"):
        mono = _n("nfc+greek-monotonic", use)
        assert mono("Ἐν ἀρχῇ ἦν ὁ λόγος") == "Εν αρχή ήν ο λόγος"
        assert mono("ᾠδὴ τῷ Ῥόδῳ") == "ωδή τώ Ρόδω"  # no iota subscript; τῷ keeps an accent
        assert mono("ῒ ῗ ϊ ΐ") == "ΐ ΐ ϊ ΐ"                                              # the diaeresis stays
        assert mono("Ἀθῆναι") == "Αθήναι"
        assert mono("\u03B1\u0313\u0301") == mono("\u1F04") == "ά"  # decomposed (nfc first) or composed
        assert mono("Η Ελλάδα ΐ") == "Η Ελλάδα ΐ"                                       # monotonic: unchanged
    assert catalog().strategy("greek-monotonic").text("ὰ") == "ά"


def test_cyrillic_prereform():
    old = _n("cyrillic-prereform", "output")
    assert old("міръ Міръ") == "мир Мир"
    assert old("свѣтъ и міръ, вѣра. ѲЕДОРЪ Ѳома") == "свет и мир, вера. ФЕДОР Фома"
    assert old("объявленіе подъѣздъ") == "объявление подъезд"                           # ъ inside a word stays
    assert old("сѷнодъ мѵро Ѵ") == "синод миро И"
    assert old("какъ-то") == "как-то" and old("домъ\n") == "дом\n"
    assert old("съѣздъ 1ъ ъ") == "съезд 1ъ ъ"                                            # after no letter: kept
    assert catalog().normalization("cyrillic-prereform").languages == ("ru",)


def test_composite_strategies_of_the_new_normalizations():
    c = catalog()
    s = c.strategy("nfc+arabic-tatweel+arabic-marks")
    assert s.use == "comparison" and s.text("كِتَـــابٌ") == "كتاب"
    assert [n.id for n in s.normalizations] == ["nfc", "arabic-tatweel", "arabic-marks"]
    out = c.strategy("nfc+arabic-tatweel+persian-arabic-letters")
    assert out.use == "output" and out.text("كتـــاب علي") == "کتاب علی"
    assert c.strategy("nfc+arabic-marks+arabic-letters+casefold").text("إِسْلَامٌ") == "اسلام"
    assert c.strategy("nfc+hebrew-points+whitespace").text("  שָׁלוֹם  עוֹלָם ") == "שלום עולם"
    assert c.strategy("nfc+cyrillic-prereform+casefold").text("ВѢРА") == "вера"
    for nid, scripts in (("arabic-tatweel", ("Arab",)), ("hebrew-points", ("Hebr",)),
                         ("greek-monotonic", ("Grek",)), ("cyrillic-prereform", ("Cyrl",))):
        assert tuple(c.normalizations[nid][1].scripts) == scripts
