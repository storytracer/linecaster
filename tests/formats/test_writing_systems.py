"""Languages, scripts and directions in ALTO, PAGE-XML and hOCR: what the writers write of recorded values, what the
readers record of a file's attributes, and PAGE's language and script tables."""
from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from linecaster.data import Annotator, Source, Transcription
from linecaster.data.transcription import Word
from linecaster.formats import _languages as L, from_alto, from_hocr, from_page, to_alto, to_hocr, to_page
from linecaster.testing import box

SCHEMAS = Path(__file__).parents[1] / "schemas"
SCHEMES = ("language", "script", "direction")


def _schema(name: str):
    path = SCHEMAS / name
    if not path.exists():
        pytest.skip(f"schema {name} not available")
    return etree.XMLSchema(etree.parse(str(path)))


def _words(text: str, x: int, y: int) -> list[Word]:
    out = []
    for w in text.split():
        out.append(Word(text=w, box=[x, y, 20 * len(w), 30]))
        x += 20 * len(w) + 10
    return out


def mixed_page() -> Transcription:
    """An English page (Latin script, left to right) with a German word in an English line, an Arabic region (right
    to left) and a Japanese region set vertically."""
    t = Transcription(source=Source(image_width=1000, image_height=1400),
                      annotators=[Annotator(kind="model", step="recognition", name="test")])
    for k, v in zip(SCHEMES, ("en", "Latn", "horizontal-lr")):
        t.classify(0, "", k, v)
    t.add_region(0, "r_en", [100, 100, 800, 40], box(100, 100, 800, 40), role="text")
    ln = t.add_line(0, "l_en", [100, 100, 800, 40], box(100, 100, 800, 40), region="r_en")
    t.read(0, ln, "a Weltanschauung of sorts", words=_words("a Weltanschauung of sorts", 100, 105))
    t.classify(0, "l_en/1", "language", "de")
    t.add_region(0, "r_ar", [100, 200, 800, 40], box(100, 200, 800, 40), role="text")
    for k, v in zip(SCHEMES, ("ar", "Arab", "horizontal-rl")):
        t.classify(0, "r_ar", k, v)
    ln = t.add_line(0, "l_ar", [100, 200, 800, 40], box(100, 200, 800, 40), region="r_ar")
    t.read(0, ln, "مرحبا بالعالم", words=_words("مرحبا بالعالم", 100, 205))
    t.add_region(0, "r_ja", [800, 300, 100, 900], box(800, 300, 100, 900), role="text")
    for k, v in zip(SCHEMES, ("ja", "Jpan", "vertical-rl")):
        t.classify(0, "r_ja", k, v)
    for i, text in enumerate(("縦書きの", "文章です")):
        ln = t.add_line(0, f"l_ja{i}", [850 - 50 * i, 300, 40, 400], box(850 - 50 * i, 300, 40, 400),
                        region="r_ja", text=text)
    t.add_order(0, ["r_en", "r_ar", "r_ja"], ["l_en", "l_ar", "l_ja0", "l_ja1"])
    return t


TARGETS = ("r_en", "r_ar", "r_ja", "l_en", "l_ar", "l_ja0", "l_ja1", "l_en/0", "l_en/1", "l_ar/0")


def resolved(t: Transcription, targets=TARGETS) -> dict:
    return {(target, k): t.written(target, k) for target in targets for k in SCHEMES}


FORMATS = {"alto": (to_alto, from_alto), "page": (to_page, from_page), "hocr": (to_hocr, from_hocr)}


@pytest.mark.parametrize("fmt", list(FORMATS))
def test_round_trip(fmt):
    t = mixed_page()
    to, fr = FORMATS[fmt]
    got = fr(to(t))
    assert resolved(got) == resolved(t)
    assert got.language("l_en/1") == "de" and got.language("l_en/0") == "en"
    assert got.direction("l_ja1") == "vertical-rl" and got.script("l_ar/0") == "Arab"
    page = ("language",) if fmt == "alto" else SCHEMES        # ALTO's Page holds a language only
    assert [got.written("", k) for k in page] == [t.written("", k) for k in page]
    # each value is recorded once, on the narrowest target the file names
    assert not got.classifications_of("l_ar", "language") and not got.classifications_of("l_en/0", "language")
    assert fr(to(got)).classifications == got.classifications          # stable


def _attrs(xml: bytes, tag: str) -> dict[str, dict[str, str]]:
    root = etree.fromstring(xml)
    return {el.get("id") or el.get("ID"): dict(el.attrib) for el in root.iter(f"{{*}}{tag}")}


def test_page_attributes_validate():
    xml = to_page(mixed_page())
    page = _attrs(xml, "Page")[None]
    assert (page["primaryLanguage"], page["primaryScript"], page["readingDirection"], page["textLineOrder"]) == \
        ("English", "Latn - Latin", "left-to-right", "top-to-bottom")
    regions = _attrs(xml, "TextRegion")
    assert "primaryLanguage" not in regions["r_en"] and "readingDirection" not in regions["r_en"]
    assert {k: regions["r_ar"][k] for k in ("primaryLanguage", "primaryScript", "readingDirection",
                                            "textLineOrder")} == \
        {"primaryLanguage": "Arabic", "primaryScript": "Arab - Arabic", "readingDirection": "right-to-left",
         "textLineOrder": "top-to-bottom"}
    assert (regions["r_ja"]["primaryLanguage"], regions["r_ja"]["primaryScript"], regions["r_ja"]["readingDirection"],
            regions["r_ja"]["textLineOrder"]) == ("Japanese", "Jpan - Japanese", "top-to-bottom", "right-to-left")
    assert _attrs(xml, "Word")["l_en_w1"]["language"] == "German"
    assert all("language" not in a and "primaryLanguage" not in a for k, a in _attrs(xml, "TextLine").items())
    assert not any(f"&quot;{k}&quot;".encode() in xml for k in SCHEMES)       # PAGE holds all of it
    schema = _schema("pagecontent-2019-07-15.xsd")
    assert schema.validate(etree.fromstring(xml)), schema.error_log


def test_alto_attributes_validate():
    xml = to_alto(mixed_page())
    assert _attrs(xml, "Page")["page_1"]["LANG"] == "en"
    blocks = _attrs(xml, "TextBlock")
    assert "LANG" not in blocks["r_en"] and blocks["r_en"]["BASEDIRECTION"] == "ltr"   # the page's direction
    assert (blocks["r_ar"]["LANG"], blocks["r_ar"]["BASEDIRECTION"]) == ("ar", "rtl")
    assert (blocks["r_ja"]["LANG"], blocks["r_ja"]["BASEDIRECTION"]) == ("ja", "ttb")
    assert _attrs(xml, "String")["l_en_w1"]["LANG"] == "de"
    assert "BASEDIRECTION" not in _attrs(xml, "TextLine")["l_ja0"]
    schema = _schema("alto-4-4.xsd")
    for data in (xml, to_alto(mixed_page(), extensions=False)):
        assert schema.validate(etree.fromstring(data)), schema.error_log


def test_hocr_attributes():
    xml = to_hocr(mixed_page())
    root = etree.fromstring(xml)
    assert root.get("lang") == "en"
    by_id = {el.get("id"): el for el in root.iter() if el.get("id")}
    assert by_id["page_1"].get("dir") == "ltr"
    assert (by_id["r_ar"].get("lang"), by_id["r_ar"].get("dir")) == ("ar", "rtl")
    assert (by_id["r_ja"].get("lang"), by_id["r_ja"].get("style")) == ("ja", "writing-mode: vertical-rl")
    assert by_id["l_en_w1"].get("lang") == "de" and by_id["l_en"].get("lang") is None
    caps = next(m.get("content") for m in root.iter("{*}meta") if m.get("name") == "ocr-capabilities")
    assert "ocrp_lang" in caps.split() and "ocrp_dir" in caps.split()


@pytest.mark.parametrize("fmt", list(FORMATS))
def test_without_recorded_values_nothing_is_written(fmt):
    t = mixed_page()
    t.classifications = [c for c in t.classifications if c.scheme not in SCHEMES]
    xml = FORMATS[fmt][0](t)
    for attr in (b"lang=", b"LANG=", b"dir=", b"writing-mode", b"BASEDIRECTION", b"Language=", b"Script=",
                 b"readingDirection", b"textLineOrder", b"language="):
        assert attr not in xml, attr
    assert not [c for c in FORMATS[fmt][1](xml).classifications if c.scheme in SCHEMES]


@pytest.mark.parametrize("fmt", list(FORMATS))
def test_values_the_format_lacks_round_trip_in_the_extension(fmt):
    t = mixed_page()
    t.classify(0, "r_en", "language", "grc")            # no PAGE name
    t.classify(0, "l_ar", "language", "ar-EG")          # PAGE: Arabic, the region in the extension
    t.classify(0, "r_ja", "script", "Zanb")             # not in PAGE's 2016 list
    got = FORMATS[fmt][1](FORMATS[fmt][0](t))
    assert (got.language("l_en/0"), got.language("l_ar"), got.script("l_ja0")) == ("grc", "ar-EG", "Zanb")


def test_page_language_without_a_page_name_validates():
    t = mixed_page()
    next(c for c in t.classifications if c.target == "" and c.scheme == "language").value = "grc"
    xml = to_page(t)
    assert b"primaryLanguage=\"English\"" not in xml and from_page(xml).language() == "grc"
    schema = _schema("pagecontent-2019-07-15.xsd")
    assert schema.validate(etree.fromstring(xml)), schema.error_log


def test_page_without_extensions_leaves_out_what_it_cannot_name():
    t = mixed_page()
    t.classify(0, "r_en", "language", "grc")
    got = from_page(to_page(t, extensions=False))
    assert got.language("r_en") == "en" and got.language("r_ar") == "ar"


PAGE_FOREIGN = """<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">
 <Metadata><Creator>x</Creator><Created>2020-01-01T00:00:00</Created><LastChange>2020-01-01T00:00:00</LastChange>
 </Metadata>
 <Page imageFilename="p.png" imageWidth="1000" imageHeight="1000" primaryLanguage="German" readingDirection="left-to-right"
       secondaryLanguage="Latin">
  <TextRegion id="r1" primaryLanguage="Hebrew" readingDirection="right-to-left" secondaryScript="Latn - Latin">
   <Coords points="0,0 500,0 500,100 0,100"/>
   <TextLine id="l1"><Coords points="0,0 500,0 500,50 0,50"/>
    <Word id="w1" language="Latin" primaryScript="Latn - Latin"><Coords points="0,0 50,0 50,50 0,50"/>
     <TextEquiv><Unicode>lux</Unicode></TextEquiv></Word>
    <TextEquiv><Unicode>lux</Unicode></TextEquiv>
   </TextLine>
   <TextRegion id="r1a"><Coords points="0,50 500,50 500,100 0,100"/>
    <TextLine id="l1a" primaryLanguage="other"><Coords points="0,50 500,50 500,90 0,90"/>
     <TextEquiv><Unicode>x</Unicode></TextEquiv></TextLine>
   </TextRegion>
  </TextRegion>
  <TextRegion id="r2" primaryLanguage="Japanese" primaryScript="Jpan - Japanese" readingDirection="top-to-bottom"
              textLineOrder="right-to-left">
   <Coords points="900,0 1000,0 1000,800 900,800"/>
   <TextLine id="l2" readingDirection="top-to-bottom"><Coords points="950,0 1000,0 1000,800 950,800"/>
    <TextEquiv><Unicode>縦</Unicode></TextEquiv></TextLine>
  </TextRegion>
  <TextRegion id="r3" readingDirection="top-to-bottom" textLineOrder="top-to-bottom">
   <Coords points="0,900 500,900 500,950 0,950"/>
  </TextRegion>
 </Page>
</PcGts>
""".encode()


def test_page_foreign():
    t = from_page(PAGE_FOREIGN)
    assert (t.language(), t.direction(), t.script()) == ("de", "horizontal-lr", None)
    assert t.source.extensions["page__secondary_language"] == "Latin"
    assert (t.language("r1"), t.direction("r1"), t.language("l1"), t.language("l1/0"), t.script("l1/0")) == \
        ("he", "horizontal-rl", "he", "la", "Latn")
    assert t.region("r1").extensions == {"page__secondary_script": "Latn - Latin"}
    # a nested region inherits what the region it lies in says; "other" names no language
    assert t.language("r1a") == "he" and t.direction("r1a") == "horizontal-rl"
    assert t.language("l1a") == "he" and t.line("l1a").extensions == {"page__language": "other"}
    assert (t.language("l2"), t.script("l2"), t.direction("l2")) == ("ja", "Jpan", "vertical-rl")
    assert not t.classifications_of("l2", "direction")          # top-to-bottom within a vertical region
    # a combination that makes no direction is kept as it is, and the page's holds
    assert t.direction("r3") == "horizontal-lr"
    assert t.region("r3").extensions == {"page__reading_direction": "top-to-bottom",
                                         "page__text_line_order": "top-to-bottom"}


ALTO_FOREIGN = """<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v4#">
 <Description><MeasurementUnit>pixel</MeasurementUnit></Description>
 <Layout><Page ID="p1" PHYSICAL_IMG_NR="1" WIDTH="1000" HEIGHT="1000" LANG="ger" OTHERLANGS="la he"><PrintSpace>
  <TextBlock ID="b1" HPOS="0" VPOS="0" WIDTH="500" HEIGHT="100">
   <TextLine ID="t1" HPOS="0" VPOS="0" WIDTH="500" HEIGHT="50">
    <String ID="s1" CONTENT="Sonne" HPOS="0" VPOS="0" WIDTH="100" HEIGHT="50"/><SP/>
    <String ID="s2" CONTENT="sol" LANG="lat" HPOS="120" VPOS="0" WIDTH="100" HEIGHT="50"/>
   </TextLine>
  </TextBlock>
  <TextBlock ID="b2" HPOS="0" VPOS="200" WIDTH="500" HEIGHT="100" LANG="he" BASEDIRECTION="rtl">
   <TextLine ID="t2" HPOS="0" VPOS="200" WIDTH="500" HEIGHT="50" LANG="yi">
    <String CONTENT="x" HPOS="0" VPOS="200" WIDTH="500" HEIGHT="50"/></TextLine>
  </TextBlock>
  <TextBlock ID="b3" HPOS="900" VPOS="0" WIDTH="100" HEIGHT="800" LANG="ja" BASEDIRECTION="ttb">
   <TextLine ID="t3" HPOS="950" VPOS="0" WIDTH="50" HEIGHT="800" BASEDIRECTION="ttb">
    <String CONTENT="縦" HPOS="950" VPOS="0" WIDTH="50" HEIGHT="800"/></TextLine>
  </TextBlock>
 </PrintSpace></Page></Layout>
</alto>
""".encode()


def test_alto_foreign():
    t = from_alto(ALTO_FOREIGN)
    assert t.language() == "de" and t.source.extensions["alto__other_languages"] == "la he"
    assert (t.language("t1"), t.language("t1/0"), t.language("t1/1")) == ("de", "de", "la")
    assert (t.language("b2"), t.direction("b2"), t.language("t2"), t.direction("t2")) == \
        ("he", "horizontal-rl", "yi", "horizontal-rl")
    # ttb says vertical, not the order of the columns: no direction, the attribute kept
    assert t.language("t3") == "ja" and t.direction("b3") is None and t.direction("t3") is None
    assert t.region("b3").extensions == {"alto__base_direction": "ttb"}
    assert t.line("t3").extensions == {"alto__base_direction": "ttb"}


HOCR_FOREIGN = """<html xmlns="http://www.w3.org/1999/xhtml" lang="en"><head><title></title></head><body>
<div class="ocr_page" id="page_1" title="bbox 0 0 1000 1000">
 <div class="ocr_carea" id="b1" title="bbox 0 0 500 100">
  <p class="ocr_par" lang="eng" title="bbox 0 0 500 100">
   <span class="ocr_line" id="l1" title="bbox 0 0 500 50"><span class="ocrx_word" id="w1" title="bbox 0 0 90 50">a</span>
    <span class="ocrx_word" id="w2" lang="deu" title="bbox 100 0 200 50">Zeitgeist</span></span>
  </p>
 </div>
 <div class="ocr_carea" id="b2" dir="rtl" title="bbox 0 200 500 300">
  <p class="ocr_par" lang="ara" title="bbox 0 200 500 300">
   <span class="ocr_line" id="l2" title="bbox 0 200 500 250"><span class="ocrx_word" title="bbox 0 200 500 250">س</span></span>
  </p>
 </div>
 <div class="ocr_carea" id="b3" lang="ja" style="color: red; writing-mode: vertical-rl" title="bbox 900 0 1000 800">
  <span class="ocr_line" id="l3" title="bbox 950 0 1000 800">縦</span>
  <span class="ocr_line" id="l4" style="writing-mode: horizontal-tb" title="bbox 900 0 950 30">AB</span>
 </div>
</div></body></html>""".encode()


def test_hocr_foreign():
    t = from_hocr(HOCR_FOREIGN)
    assert t.language() == "en" and t.direction() is None
    assert (t.language("l1/0"), t.language("l1/1")) == ("en", "de")
    assert not t.classifications_of("l1", "language")               # the paragraph's eng is the page's en
    assert (t.language("b2"), t.direction("b2"), t.language("l2"), t.direction("l2")) == \
        ("en", "horizontal-rl", "ar", "horizontal-rl")
    assert (t.language("l3"), t.direction("l3"), t.direction("l4")) == ("ja", "vertical-rl", "horizontal-lr")


def test_page_tables():
    assert len(L.PAGE_LANGUAGES) == 187 and len(L.PAGE_SCRIPTS) == 180
    for name, tag in (("German", "de"), ("Arabic", "ar"), ("Japanese", "ja"), ("English", "en"), ("Greek", "el"),
                      ("Latin", "la"), ("Cantonese", "yue"), ("Hebrew", "he")):
        assert L.from_page_language(name) == tag and L.page_language(tag) == name
    assert L.from_page_language("Cambodian") == "km" and L.page_language("km") == "Khmer"
    assert L.from_page_language("other") is None and L.page_language("grc") is None
    assert L.page_language("de-1901") == "German" and L.page_language("deu") == "German"
    for value, code in (("Latn - Latin", "Latn"), ("Hani - Han (Hanzi, Kanji, Hanja)", "Hani"),
                        ("Jpan - Japanese", "Jpan"), ("Arab - Arabic", "Arab"), ("Latf - Latin (Fraktur variant)",
                                                                             "Latf")):
        assert L.from_page_script(value) == code and L.page_script(code) == value
    assert L.from_page_script("other") is None and L.page_script("Zanb") is None
    assert (L.canonical("eng"), L.canonical("ger"), L.canonical("deu-DE"), L.canonical("grc"),
            L.canonical("en_US"), L.canonical("fra/lat")) == ("en", "de", "de-DE", "grc", "en-US", None)


def test_alto_keeps_the_page_s_script_and_direction_on_the_page():
    from lxml import etree

    from linecaster.testing.scripts import script_page

    for sid, direction, script in (("japanese", "vertical-rl", "Jpan"), ("arabic", "horizontal-rl", "Arab")):
        xml = to_alto(script_page(sid))
        back = from_alto(xml)
        assert (back.direction(""), back.script("")) == (direction, script)
        assert not [c for c in back.classifications if c.scheme in ("direction", "script") and c.target]
        assert _schema("alto-4-4.xsd").validate(etree.fromstring(xml))
        assert from_alto(to_alto(script_page(sid), extensions=False)).direction("r0") == (
            "horizontal-rl" if sid == "arabic" else None)      # without the extension: BASEDIRECTION only
