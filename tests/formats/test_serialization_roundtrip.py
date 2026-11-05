"""Semantic round trips: from_x(to_x(t)) reproduces structure, text, geometry (to the format's
precision), confidences, ids and reading order."""
from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from linecaster.data import Line, Region, StepInfo, Transcription, Word
from linecaster.formats import _xml as X, from_alto, from_hocr, from_page, to_alto, to_hocr, to_page
from linecaster.formats.hocr import quantize_confidence

from conftest import make_transcription

SCHEMAS = Path(__file__).parents[1] / "schemas"


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
    qz = X.Quantizer(0, clamp=(fmt == "page"))
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
            ln.confidence = quantize_confidence(ln.confidence)
            for w in ln.words:
                w.confidence = quantize_confidence(w.confidence)
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
    assert [steps(m) for m in got.steps] == [steps(m) for m in want.steps]


def steps(m: StepInfo) -> dict:
    """What a page file keeps of a step: everything but the measurements."""
    return m.model_dump(exclude={"measurements"})


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
    """A second round trip changes nothing (the first one already quantized)."""
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


def test_page_clamps_negative_coordinates():
    t = make_transcription()
    t.regions[0].polygon[0] = [-3.4, -1.0]
    t.lines[0].baseline[0] = [-2.0, 125.0]
    got = from_page(to_page(t))
    assert got.regions[0].polygon[0] == [0.0, 0.0]
    assert got.lines[0].baseline[0] == [0.0, 125.0]
    page = _schema("pagecontent-2019-07-15.xsd")
    assert page.validate(etree.fromstring(to_page(t))), page.error_log


def test_output_is_deterministic(transcription):
    for to in (to_alto, to_page, to_hocr):
        assert to(transcription) == to(make_transcription())


def test_transcription_import_stays_light():
    import subprocess
    import sys
    code = ("import sys, linecaster.data; "
            "bad = [m for m in ('datatrove', 'saturate', 'torch', 'kraken') if m in sys.modules]; "
            "print(bad); sys.exit(1 if bad else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def _random_transcription(seed: int) -> Transcription:
    import random
    rnd = random.Random(seed)

    def f(lo=0.0, hi=2000.0):
        v = rnd.uniform(lo, hi)
        return rnd.choice([float(int(v)), round(v, 2), v])

    def box():
        return [f(), f(), f(1, 500), f(1, 200)]

    def pts(n):
        return [[f(), f()] for _ in range(n)]

    def conf():
        return rnd.choice([None, rnd.random(), 1.0, 0.0])

    labels = ["text", "title", "section_header", "page_header", "page_footer", "picture", "table",
              "formula", "footnote", "caption", "list_item", "chart", "code"]
    regions = []
    order = list(range(rnd.randint(0, 5)))
    rnd.shuffle(order)
    for i, ro in enumerate(order):
        regions.append(Region(id=f"r{i}", label=rnd.choice(labels), raw_label=rnd.choice(["", "x_y", "heading"]),
                              polygon=pts(rnd.randint(3, 6)), bbox=box(), score=conf(),
                              reading_order=rnd.choice([ro, ro * 3, None]),
                              heading_level=rnd.choice([None, 1, 2])))
    lines = []
    n = rnd.randint(0, 10)
    ranks = list(range(n))
    rnd.shuffle(ranks)
    for i in range(n):
        words = []
        for k in range(rnd.choice([0, 0, 1, 3])):
            words.append(Word(id=f"l{i}_w{k}", text=rnd.choice(["a", "bc-", "Déjà", "x y", ""]),
                              bbox=rnd.choice([None, box()]), confidence=conf(),
                              hyphen=rnd.random() < 0.2,
                              alternatives=rnd.choice([[], ["alt"]])))
        text = rnd.choice([None, "", " ".join(w.text for w in words), "free  text"])
        lines.append(Line(id=f"l{i}", region_id=rnd.choice([None] + [r.id for r in regions]),
                          reading_order=ranks[i], row=rnd.randint(0, 3), bbox=box(),
                          polygon=rnd.choice([None, pts(4)]), baseline=rnd.choice([None, pts(2), pts(3)]),
                          score=conf(), text=text, confidence=conf(), words=words,
                          alternatives=rnd.choice([[], ["other"]])))
    values = [None, True, False, 0, 16, 0.1, -2.5, "", "16", "true", "null", "medium", "a;b {c}", ' "x" ',
              "line\nbreak", "Déjà vu", [1, "2"], {"nested": {"k": [None]}}]
    steps = []
    for i in range(rnd.choice([0, 1, 3])):
        steps.append(StepInfo(
            step=rnd.choice(["layout", "lines", "recognition", "unicode", "typography", "page"]),
            name=rnd.choice(["kraken-ppocrv6-medium", "PP-DocLayoutV3", "Qwen/Qwen3-VL 8B", "naïve name"]),
            engine=rnd.choice([None, "kraken.recognition.v1", "typography.ratios.v1"]),
            revision=rnd.choice([None, "0123abcd", "10.5281/zenodo.1"]),
            preset=rnd.choice([None, f"preset-{i}@{rnd.randint(1, 9)}"]),
            preset_sha256=rnd.choice([None, "sha256:" + "0f" * 32]),
            backend=rnd.choice([None, "in-process", "served http://127.0.0.1:8100/v1 (recognition)"]),
            settings={f"k{j}": rnd.choice(values) for j in range(rnd.choice([0, 1, 4]))},
            measurements=rnd.choice([{}, {"seconds": 0.5}, {"seconds": 1, "datetime": "2026-11-03T12:00:00Z"}]),
        ))
    return Transcription(regions=regions, lines=lines, steps=steps, source=Transcription().source.model_copy(
        update={"image_width": 3000, "image_height": 3000}))


@pytest.mark.parametrize("fmt", list(FORMATS))
@pytest.mark.parametrize("seed", range(300))
def test_random_roundtrip(fmt, seed):
    t = _random_transcription(seed)
    assert_same(roundtrip(t, fmt), _expected_for(t, fmt))
    if seed % 10 == 0 and fmt in ("alto", "page"):
        to = to_alto if fmt == "alto" else to_page
        schema = _cached_schema("alto-4-4.xsd" if fmt == "alto" else "pagecontent-2019-07-15.xsd")
        assert schema.validate(etree.fromstring(to(t))), schema.error_log


_SCHEMA_CACHE: dict = {}


def _cached_schema(name):
    if name not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[name] = _schema(name)
    return _SCHEMA_CACHE[name]
