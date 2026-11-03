"""Semantic round trips: from_x(to_x(t)) reproduces structure, text, geometry (to the format's
precision), confidences, ids and reading order."""
from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from linecaster.transcription import (Line, Region, Transcription, Word, from_alto, from_hocr,
                                      from_page, to_alto, to_hocr, to_page)
from linecaster.transcription import _xml as X
from linecaster.transcription.hocr import quantise_confidence

from conftest import make_transcription

SCHEMAS = Path(__file__).parent / "schemas"


def _schema(name: str):
    path = SCHEMAS / name
    if not path.exists():
        pytest.skip(f"schema {name} not available")
    try:
        return etree.XMLSchema(etree.parse(str(path)))
    except etree.XMLSchemaParseError as e:     # e.g. an import that cannot be resolved offline
        pytest.skip(f"schema {name} cannot be loaded: {e}")


def expected(t: Transcription, fmt: str) -> Transcription:
    """What a reader gets back: integer geometry for PAGE (clamped at 0) and hOCR, integer-percent
    confidences for hOCR; everything else unchanged."""
    e = t.model_copy(deep=True)
    if fmt in ("alto", None):
        return e
    qz = X.Quantiser(0, clamp=(fmt == "page"))
    for r in e.regions:
        r.polygon = qz.points(r.polygon)
        r.bbox = qz.box(r.bbox)
    for ln in e.lines:
        ln.bbox = qz.box(ln.bbox)
        ln.polygon = qz.points(ln.polygon)
        ln.baseline = qz.points(ln.baseline)
        for w in ln.words:
            w.bbox = qz.box(w.bbox) if w.bbox is not None else None
        if fmt == "hocr":
            ln.confidence = quantise_confidence(ln.confidence)
            for w in ln.words:
                w.confidence = quantise_confidence(w.confidence)
    return e


FORMATS = {
    "alto": (to_alto, from_alto),
    "alto0": (lambda t, **k: to_alto(t, precision=0, **k), from_alto),
    "page": (to_page, from_page),
    "hocr": (to_hocr, from_hocr),
}


def roundtrip(t: Transcription, fmt: str) -> Transcription:
    to, fr = FORMATS[fmt]
    return fr(to(t))


def assert_same(got: Transcription, want: Transcription) -> None:
    """Equal as sets of regions and lines (readers return them in document order, which can differ
    from the list order of the original; reading order is in the fields)."""
    assert sorted(r.id for r in got.regions) == sorted(r.id for r in want.regions)
    assert sorted(ln.id for ln in got.lines) == sorted(ln.id for ln in want.lines)
    got_r = {r.id: r for r in got.regions}
    for w in want.regions:
        assert got_r[w.id] == w, f"region {w.id}"
    got_l = {ln.id: ln for ln in got.lines}
    for w in want.lines:
        assert got_l[w.id] == w, f"line {w.id}"
    assert got.text == want.text


def _expected_for(t, fmt):
    if fmt == "alto0":
        e = expected(t, "hocr")       # integer geometry, unclamped
        for ln, o in zip(e.lines, t.lines):
            ln.confidence = o.confidence
            for w, ow in zip(ln.words, o.words):
                w.confidence = ow.confidence
        return e
    return expected(t, fmt)


@pytest.mark.parametrize("fmt", list(FORMATS))
def test_roundtrip_fixture(transcription, fmt):
    got = roundtrip(transcription, fmt)
    assert_same(got, _expected_for(transcription, fmt))
    assert got.source.kind == "converted"
    assert got.source.image_width == 1600 and got.source.image_height == 2400


@pytest.mark.parametrize("fmt", list(FORMATS))
def test_roundtrip_is_stable(transcription, fmt):
    """A second round trip changes nothing (the first one already quantised)."""
    once = roundtrip(transcription, fmt)
    once.source = transcription.source
    assert_same(roundtrip(once, fmt), once)


@pytest.mark.parametrize("fmt", list(FORMATS))
def test_lines_only_page(fmt):
    """A line step's output without any layout regions: every line is region-less."""
    t = make_transcription()
    t.regions = []
    for ln in t.lines:
        ln.region_id = None
    t.lines.sort(key=lambda ln: ln.reading_order)
    for i, ln in enumerate(t.lines):
        ln.row = i
    got = roundtrip(t, fmt)
    assert got.regions == []
    assert_same(got, _expected_for(t, fmt))


@pytest.mark.parametrize("fmt", list(FORMATS))
def test_irregular_order_survives(fmt):
    """Orders the nesting cannot express (region without order, line ranks not following the
    regions, rows that are not positions) still come back."""
    t = make_transcription()
    t.regions[3].reading_order = None          # the picture has no order
    t.regions[4].reading_order = 7             # gaps in the region order
    t.lines[3].row = 5                         # row is not the position in the region
    t.lines[0].reading_order = 20              # running head read last
    got = roundtrip(t, fmt)
    assert_same(got, _expected_for(t, fmt))


@pytest.mark.parametrize("fmt", list(FORMATS))
def test_words_edge_cases(fmt):
    t = make_transcription()
    ln = t.lines[2]
    ln.words[1].hyphen = True                  # a hyphen flag mid-line
    ln.words[2].bbox = None                    # a word without a box
    ln.words[3].confidence = None
    ln.text = None if fmt != "page" else ln.text
    got = roundtrip(t, fmt)
    assert_same(got, _expected_for(t, fmt))


@pytest.mark.parametrize("fmt", list(FORMATS))
def test_unknown_label_and_raw_label(fmt):
    t = make_transcription()
    t.regions[2].label = "handwritten_text"
    t.regions[2].raw_label = "aside text; {odd}"
    t.regions[4].raw_label = ""
    t.regions[3].label = "chart"
    got = roundtrip(t, fmt)
    assert_same(got, _expected_for(t, fmt))


def test_alto_float_geometry_is_exact(transcription):
    got = from_alto(to_alto(transcription))
    assert got.regions[1].polygon == transcription.regions[1].polygon
    assert got.lines[1].baseline == [[312.5, 300.25], [800.0, 301.5], [1288.0, 302.75]]


def test_alto_and_page_validate(transcription):
    alto = _schema("alto-4-4.xsd")
    page = _schema("pagecontent-2019-07-15.xsd")
    for data in (to_alto(transcription), to_alto(transcription, precision=0),
                 to_alto(transcription, extensions=False)):
        doc = etree.fromstring(data)
        assert alto.validate(doc), alto.error_log
    for data in (to_page(transcription), to_page(transcription, extensions=False)):
        doc = etree.fromstring(data)
        assert page.validate(doc), page.error_log


def test_irregular_output_validates():
    t = make_transcription()
    t.regions = []
    for ln in t.lines:
        ln.region_id = None
    t.lines[0].reading_order = 30
    alto = _schema("alto-4-4.xsd")
    page = _schema("pagecontent-2019-07-15.xsd")
    assert alto.validate(etree.fromstring(to_alto(t))), alto.error_log
    assert page.validate(etree.fromstring(to_page(t))), page.error_log


@pytest.mark.parametrize("fmt", ["alto", "page", "hocr"])
def test_without_extensions_keeps_the_native_parts(transcription, fmt):
    to, fr = {"alto": (to_alto, from_alto), "page": (to_page, from_page), "hocr": (to_hocr, from_hocr)}[fmt]
    data = to(transcription, extensions=False)
    assert b"linecaster\":" not in data and b"lcx_" not in data
    got = fr(data)
    # the orphan line's synthetic block comes back as a region in ALTO and PAGE
    want = ["page_header_0", "doc_title_1", "text_2", "image_3", "footnote_4"]
    if fmt != "hocr":
        want.insert(4, "lc_block_0")
    assert [r.id for r in got.regions] == want
    ids = [ln.id for ln in got.lines]
    assert ids == [ln.id for ln in sorted(transcription.lines, key=lambda ln: ln.reading_order)]
    by_id = {ln.id: ln for ln in got.lines}
    assert by_id["l0"].text == "12 THE BOTANIST"
    assert [w.id for w in by_id["l2"].words] == [f"l2_w{i}" for i in range(6)]
    assert by_id["l2"].words[-1].text == "col-"


def test_alto_structure(transcription):
    root = etree.fromstring(to_alto(transcription))
    ns = {"a": "http://www.loc.gov/standards/alto/ns-v4#"}
    assert root.get("SCHEMAVERSION") == "4.4"
    assert root.find("a:Description/a:MeasurementUnit", ns).text == "pixel"
    blocks = root.findall(".//a:PrintSpace/*", ns)
    assert [b.get("ID") for b in blocks] == ["page_header_0", "doc_title_1", "text_2", "image_3",
                                             "lc_block_0", "footnote_4"]
    assert blocks[3].tag.endswith("Illustration")
    hyp = root.find(".//a:TextLine[@ID='l2']/a:HYP", ns)
    assert hyp.get("CONTENT") == "-"
    assert root.find(".//a:String[@ID='l2_w5']", ns).get("CONTENT") == "col"
    refs = [e.get("REF") for e in root.findall("a:ReadingOrder/a:OrderedGroup/a:ElementRef", ns)]
    assert refs == ["page_header_0", "doc_title_1", "text_2", "image_3", "lc_block_0", "footnote_4"]


def test_page_structure(transcription):
    root = etree.fromstring(to_page(transcription))
    ns = {"p": "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15"}
    regions = root.findall("p:Page/*", ns)
    tags = [etree.QName(r).localname for r in regions]
    assert tags == ["ReadingOrder", "TextRegion", "TextRegion", "TextRegion", "ImageRegion",
                    "TextRegion", "TextRegion"]
    assert regions[2].get("type") == "heading"
    assert regions[2].get("custom") == "structure {type:doc_title;}"
    assert regions[1].find("p:Coords", ns).get("conf") == "0.91"
    te = root.find(".//p:TextLine[@id='l1']/p:TextEquiv", ns)
    assert te.get("conf") == "0.884" and te.find("p:Unicode", ns).text == "Flora of the Northern Hills"


def test_hocr_structure(transcription):
    data = to_hocr(transcription)
    root = etree.fromstring(data)
    ns = {"h": "http://www.w3.org/1999/xhtml"}
    page = root.find(".//h:div[@class='ocr_page']", ns)
    assert page.get("title") == 'image "page_0001.webp"; bbox 0 0 1600 2400; ppageno 0'
    w = root.find(".//h:span[@id='l0_w1']", ns)
    assert w.get("class") == "ocrx_word" and w.text == "THE"
    assert w.get("title") == "bbox 190 86 280 126; x_wconf 96"
    assert root.find(".//h:div[@id='page_header_0']", ns).get("class") == "ocr_header"
    line = root.find(".//h:span[@id='l2']", ns)
    assert "baseline 0 -10" in line.get("title")
