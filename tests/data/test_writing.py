"""Writing systems in the data model: language, script and direction recorded and resolved through what encloses a
target; their values checked; a text's script and direction inferred only when asked."""
from __future__ import annotations

import pytest

from linecaster.data import Annotator, Transcription
from linecaster.data.writing import DIRECTIONS, check, is_language, is_script, language_tag
from linecaster.text.scripts import default_direction, dominant_script, first_strong_direction, script_of, scripts


def _page() -> Transcription:
    t = Transcription()
    a = t.add_annotator(Annotator(step="layout", name="test"))
    t.add_region(a, "r0", [0, 0, 100, 100], role="paragraph")
    t.add_region(a, "r0a", [0, 0, 50, 50], role="paragraph", parent="r0")
    t.add_line(a, "l0", region="r0a", text="Salam, سلام عليكم")
    t.add_line(a, "l1", text="free line")
    return t


def test_values_are_recorded_and_inherited_from_what_encloses_a_target():
    t = _page()
    assert (t.language(), t.script("l0"), t.direction("l0/0")) == (None, None, None)
    t.classify(0, "", "language", "en")
    t.classify(0, "r0", "direction", "horizontal-rl")
    t.classify(0, "r0", "language", "ar")
    t.classify(0, "l0[7:17]", "script", "Arab")
    assert t.language("l0") == "ar" and t.language("l0[0:5]") == "ar"     # line -> region r0a -> parent r0
    assert t.language("l1") == "en" and t.language("") == "en"           # no region: the page
    assert t.direction("l0/1") == "horizontal-rl" and t.direction("l1") is None
    assert t.script("l0[7:17]") == "Arab" and t.script("l0") is None
    assert t.language("p0002#l0") is None                               # another page: not resolved here


def test_a_value_that_is_none_is_refused_where_it_is_made():
    t = _page()
    for scheme, value in (("direction", "rtl"), ("script", "arabic"), ("language", "en US")):
        with pytest.raises(ValueError, match=scheme):
            t.classify(0, "", scheme, value)
    assert t.classify(0, "", "role", "anything").value == "anything"     # other schemes: free


@pytest.mark.parametrize("tag,ok", [("en", True), ("grc", True), ("de-1901", True), ("zh-Hant-TW", True),
                                    ("sr-Latn-RS", True), ("x-private", True), ("en-US-x-old", True),
                                    ("en US", False), ("", False), ("e", False), ("fra/lat", False)])
def test_language_tags_are_checked_for_well_formedness(tag, ok):
    assert is_language(tag) is ok


def test_a_source_s_language_value_is_made_a_tag_where_it_is_one():
    assert (language_tag(" en_US "), language_tag("en US"), language_tag(None)) == ("en-US", None, None)


def test_scripts_and_directions():
    assert is_script("Latn") and is_script("Jpan") and not is_script("LATN") and not is_script("Lat")
    assert check("direction", "vertical-rl") == "vertical-rl" and DIRECTIONS[0] == "horizontal-lr"


@pytest.mark.parametrize("text,script", [
    ("The ship sailed.", "Latn"), ("Ἐν ἀρχῇ ἦν ὁ λόγος", "Grek"), ("Въ началѣ бѣ слово", "Cyrl"),
    ("بسم الله الرحمن الرحيم", "Arab"), ("בְּרֵאשִׁית בָּרָא", "Hebr"), ("नमस्ते दुनिया", "Deva"),
    ("สวัสดีครับ", "Thai"), ("天地玄黃", "Hani"), ("東京は晴れです", "Jpan"), ("カタカナ と ひらがな", "Jpan"),
    ("한국어 漢字", "Kore"), ("한국어 텍스트", "Hang"), ("ᠮᠣᠩᠭᠣᠯ", "Mong"), ("12, 34.", None),
])
def test_a_text_s_dominant_script(text, script):
    assert dominant_script(text) == script


def test_script_of_a_character():
    assert (script_of("a"), script_of("ſ"), script_of("ä"), script_of("1"), script_of("́")) == (
        "Latn", "Latn", "Latn", None, None)
    assert scripts("ab αβγ") == {"Latn": 2, "Grek": 3}


@pytest.mark.parametrize("text,direction", [
    ("The ship", "ltr"), ("سلام world", "rtl"), ("1887: שלום", "rtl"), ("12, 34", None),
    ("⁧abc⁩ שלום", "rtl"),          # an isolate is skipped: its Latin does not count
    ("⁦שלום⁩ abc", "ltr"),
])
def test_first_strong_direction(text, direction):
    assert first_strong_direction(text) == direction


def test_default_directions():
    assert (default_direction("Arab"), default_direction("Hebr"), default_direction("Mong"),
            default_direction("Hani"), default_direction(None)) == ("horizontal-rl", "horizontal-rl", "vertical-lr",
                                                                   "horizontal-lr", "horizontal-lr")
