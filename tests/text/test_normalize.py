"""Normalizations and strategies (catalog kinds, linecaster.normalization.rules): each rule on hand-made cases, the lanes
rebuilt from normalizations giving the old lanes' output, latin-historic giving the old normalization table's."""
import random

import pytest

from linecaster.catalog.registry import catalog
from linecaster.errors import CatalogError
from linecaster.normalization.latex import latex_text
from linecaster.normalization.rules import StructureRule, apply_rule

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
        assert mono("ᾼ ᾈδης ᾯ ῼ") == "Α Αδης Ώ Ω"                                    # capitals with prosgegrammeni
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


def test_japanese_iteration_marks():
    out = _n("japanese-iteration-marks", "comparison")
    assert out("こゝろ たゞ 人々 カヽ ヒヾ うゞ") == "こころ ただ 人人 カカ ヒビ うゔ"
    assert out("ゝ々 はゝ") == "ゝ々 はは"                                    # nothing to repeat: kept
    with pytest.raises(CatalogError, match="not for output"):
        _n("japanese-iteration-marks", "output")


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


# ---- international typography (Omni Parse Bench's comparison fold as normalizations) and the typographic lane ----

def test_typography():
    out = _n("typography", "comparison")
    assert out("„Ja“ «oui» ‹non› ‚x‛ ꞌaˈb") == "\"Ja“ \"oui\" 'non' 'x' 'a'b"           # “ is quotes'
    assert out("5′3″ 4‴ ‶x‵ ′′ ‘‘tex’’ ``tex''") == "5'3\" 4\" \"x' \" \"tex\" \"tex\""
    assert out("−4 a⸺b ﹣1 －2") == "-4 a-b -1 -2"
    assert out("a–b a—b") == "a–b a—b"                                                  # dashes' own
    assert out("1⁄2 ½ a…b") == "1/2 ½ a...b"                                            # ½ is nfkc's
    assert out("a b c d e f g　h i​j") == "a b c d e f g h i​j"
    assert out("3·5 2∙7 a·b 3 · 5 3⋅5") == "3.5 2.7 a·b 3 · 5 3⋅5"                  # a decimal only between digits
    assert out("x≦y ♢ ∗") == "x≤y ◊ *"
    assert out("a⇒b ⟶ ➡ c⟵d ⇐ ⬆ ⇑ ⇓ ⬇ → ←") == "a→b → → c←d ← ↑ ↑ ↓ ↓ → ←"
    assert out("Straße ÆØ 12 ABC") == "Straße ÆØ 12 ABC"
    assert _n("nfkc+typography", "comparison")("½ ″") == "1/2 \""                         # what NFKC leaves
    with pytest.raises(CatalogError, match="not for output"):
        _n("typography", "output")


def test_cjk_punctuation():
    out = _n("cjk-punctuation", "comparison")
    assert out("「東京」、『大阪』。") == "\"東京\",\"大阪\"."
    assert out("【注】〔一〕《書》〈章〉") == "[注][一]\"書\"'章'"
    assert out("（括弧）！？：；，．％＝〜～") == "(括弧)!?:;,.%=~~"
    assert out("｢半角｣｡､") == "\"半角\".,"
    assert out("ＡＢ１２・ー々") == "ＡＢ１２・ー々"                              # letters, digits, marks: nfkc's or kept
    assert out("東京, 大阪. (x)") == "東京, 大阪. (x)"
    assert _n("nfkc+cjk-punctuation", "comparison")("「ＡＢ」。") == "\"AB\"."


def test_checkboxes():
    out = _n("checkboxes", "comparison")
    assert out("- [x] done [X] [checked] [CHECKED] [✓] [✗]") == "- ☒ done ☒ ☒ ☒ ☒ ☒"
    assert out("- [ ] todo [] [unchecked] [Unchecked]") == "- ☐ todo ☐ ☐ ☐"
    assert out("☑ ☒ ■ ▣ ✓ ✔ ✗ ✘") == " ".join("☒" * 8)
    assert out("☐ □ ◻ ◼ ❏ ▢ ⬜") == " ".join("☐" * 7)
    assert out("a[i] [12] [xx] [ x ] x") == "a[i] [12] [xx] [ x ] x"                  # other brackets stay


def test_footnote_markers():
    out = _n("footnote-markers", "comparison")
    assert out("12.3%[1] word[^a] x[ 12 ] y[^ 3 ] [999]") == "12.3% 1 word a x 12 y 3  999"
    assert out("[1234] [1, 2] [12a] [^abcd] [a] 1") == "[1234] [1, 2] [12a] [^abcd] [a] 1"


def test_bullets():
    out = _n("bullets", "comparison")
    assert out("• one\n  ▪ two\n◦ ‣ ▶ ∙\n●") == "  one\n    two\n  ‣ ▶ ∙\n "
    assert out("a • b\n•x\n■ box\n- dash") == "a • b\n•x\n■ box\n- dash"        # inside a line, glued, ■ and -


def test_leaders():
    out = _n("leaders", "comparison")
    assert out("Chapter 1 ........ 5") == "Chapter 1  5"
    assert out("Name: ____ here. ____") == "Name:  here.  "                       # a full stop beside a blank stays
    assert out("x . . . y ……… z ··· w") == "x  y  z  w"
    assert out("a ===== b ***** c ∗∗∗ d ——— e") == "a  b  c  d  e"
    assert out("hospital......-.-") == "hospital "                                    # dots and dashes: one run
    assert out("....... -4.8%") == " -4.8%"                                           # a sign before a digit stays
    assert out("-----5") == " 5"                                                     # glued to the run: a leader
    assert out("Wait... yes.. no -- x __ y == z ** w") == "Wait yes.. no -- x __ y == z ** w"


def test_superscript_digits():
    out = _n("superscript-digits", "comparison")
    assert out("1,240¹ 10³⁴") == "1,240 ¹ 10 ³⁴"
    assert out("m² x³ ¹2 a ¹") == "m² x³ ¹2 a ¹"                                      # only after a digit
    assert _n("superscript-digits+nfkc", "comparison")("1,240¹") == "1,240 1"
    assert _n("nfkc", "comparison")("1,240¹") == "1,2401"                               # why it runs before nfkc


def test_romanian_comma_below():
    c = catalog()
    for use in ("output", "comparison"):
        out = _n("romanian-comma-below", use)
        assert out("ştiinţă ŞŢ") == "știință ȘȚ"
        assert out("şţŞŢ") == "șțȘȚ"                           # decomposed cedillas too
        assert out("știință çÇ ğ") == "știință çÇ ğ"                                   # comma below and others stay
    assert c.normalization("romanian-comma-below").languages == ("ro",)


def test_line_end_hyphens():
    out = _n("line-end-hyphens", "comparison")
    assert out("develop-\ners") == "developers"
    assert out("Prä-\nüberlegt x‐\nyz x‑ \r\n  ab é-\nla") == "Präüberlegt xyz xab éla"  # any \p{Ll}, any hyphen
    assert out("é-\nla") == "éla"                                        # a letter with a mark before
    assert out("the A-\nTeam") == "the A-\nTeam"                                       # uppercase: stays
    assert out("page 1-\nb") == "page 1-\nb"                                           # after a digit: stays
    assert out("end-\n4 x-\n(y) x- y") == "end-\n4 x-\n(y) x- y"             # digit, punctuation, paragraph
    assert out("well-known x —\nand x–\nb") == "well-known x —\nand x–\nb"            # inside a line; dashes
    with pytest.raises(CatalogError, match="not for output"):
        _n("line-end-hyphens", "output")
    c = catalog()
    assert all("line-end-hyphens" not in [n.id for n in c.strategy(s).normalizations] for s in c.strategies)


def test_pattern_engine():
    from pydantic import ValidationError

    from linecaster.catalog.schema import Pattern

    assert Pattern(match="a").model_dump(mode="json") == {"match": "a", "flags": [], "replace": " "}
    assert Pattern(match=r"\p{Ll}", engine="regex").model_dump(mode="json")["engine"] == "regex"
    with pytest.raises(ValidationError, match="bad escape"):
        Pattern(match=r"\p{Ll}")                                                    # re has no \p
    with pytest.raises(ValidationError):
        Pattern(match="(", engine="regex")
    rule = {"patterns": [{"match": r"\p{Lu}", "flags": [], "replace": "_", "engine": "regex"},
                         {"match": "B", "flags": ["I"], "replace": "-"}]}
    assert apply_rule("aÄb", rule) == "a_-"


def test_existing_pattern_normalizations_keep_their_hashes():
    # Note: the hashes before Pattern had an engine; the default engine is left out of the functional content.
    c = catalog()
    assert {nid: c.normalization(nid).sha256 for nid in ("markup", "html-tags", "cyrillic-prereform",
                                                       "japanese-iteration-marks")} == {
        "markup": "sha256:516d354c6fdab10842f8717e472cc81326e2ca2107b6b39e257f5d789cfc12b4",
        "html-tags": "sha256:07e3aaf8543aa12583378a8f25380a28872ca7307074f35451792f892e9f2dae",
        "cyrillic-prereform": "sha256:dff7c942fda00f00f42cd594165756d1c357a91bca6f8afb5af6a8d558e8974a",
        "japanese-iteration-marks": "sha256:2b48cd7d9e26411d73b2d5db02e2ccc0a2d3e1e3c476abe08a4e0c593b62a839"}
    assert c.strategy("reading").sha256 == "sha256:48661b424f32b9d5f1772f9144802e38e3bc59793c2904802c4aca6ad4f00cb5"


def test_typographic_lane():
    c = catalog()
    lane = c.strategy("typographic", use="comparison")
    reading = [n.id for n in c.strategy("reading").normalizations]
    ids = [n.id for n in lane.normalizations]
    assert [i for i in ids if i in reading] == reading                                 # reading's, in its order
    assert ids.index("superscript-digits") < ids.index("nfkc") < ids.index("typography")
    assert ids.index("markup") < ids.index("footnote-markers") and ids[-2:] == ["casefold", "whitespace"]
    assert "line-end-hyphens" not in ids and "romanian-comma-below" not in ids
    text = lane.text
    assert text("„Ein Test“ — «oui»") == "\"ein test\" - \"oui\""
    assert text("1,240¹ und 12.3%[1] word[^a]") == "1,240 1 und 12.3% 1 word a"
    assert text("• Punkt ........ 5\n- [x] erledigt\n☑ ok [ ] offen") == "punkt 5 ☒ erledigt ☒ ok ☐ offen"
    assert text("「東京」。 ½ ３·５ a⇒b") == "\"東京\". 1/2 3.5 a→b"
    assert text("**bold** <b>x</b> $x^{2}$") == text("bold x x²")
    assert text("develop-\ners") == "develop- ers"                                     # no dehyphenation
    assert text("ştiinţă") == "ştiinţă"                                                # language-specific: opt-in
    assert text("Äpfel ＡＢ　ＣＤ") == "äpfel ab cd"
    # the same text written two ways compares equal
    assert text("Ce „mai“ face?\n• Bine ........ 3") == text('Ce "mai" face? Bine 3')
    assert c.strategy("typographic+romanian-comma-below", use="comparison").text("Ştiinţă") == "știință"
