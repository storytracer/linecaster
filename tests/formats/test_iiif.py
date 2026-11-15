"""The IIIF annotation page of a transcription: its annotations, reading it back (and foreign pages), and validity
against the IIIF Presentation 3 JSON Schema of the IIIF presentation validator, fetched at a pinned commit (the file
states no licence, so it is not copied into this repository)."""
from __future__ import annotations

import hashlib
import json
import urllib.request

import pytest

from linecaster.formats.iiif import to_annotation_page
from linecaster.testing import sample_transcription

SCHEMA_URL = ("https://raw.githubusercontent.com/IIIF/presentation-validator/"
              "455c3c325b49e61ac6c393c385d9478e68ce42bd/schema/iiif_3_0.json")
SCHEMA_SHA256 = "14dd7ee8aee25d959be4b12feddb4179c726909fc85b925f6707f4ab3bfe2ad6"
CANVAS = "https://example.org/iiif/item1/canvas/1"


def page():
    return to_annotation_page(sample_transcription(), CANVAS, "https://example.org/annotations/item1/1/ocr_new")


def test_every_region_line_and_word_is_an_annotation_on_the_canvas():
    p = page()
    by = {}
    for a in p["items"]:
        by.setdefault((a["motivation"], a.get("textGranularity")), []).append(a)
    assert len(by[("classifying", None)]) == 5
    assert len(by[("supplementing", "line")]) == 7                 # the eighth line has no reading yet
    assert by[("supplementing", "line")][0]["body"]["value"] == "12 THE BOTANIST"
    assert by[("supplementing", "line")][0]["target"] == f"{CANVAS}#xywh=130,85,400,50"
    assert by[("classifying", None)][0]["body"]["value"] == "header"
    assert all(a["generator"]["name"] == "sample" for a in p["items"])


def test_each_body_has_its_targets_language():
    """A line's and a word's body has the language its target records (its own, else its line's, region's or the
    page's); a region's body has none, and a page that records none gives none."""
    t = sample_transcription()
    assert not any("language" in a["body"] for a in page()["items"])
    t.classify(0, "", "language", "en")
    t.classify(0, "footnote_4", "language", "la")
    t.classify(0, "l1/1", "language", "de")
    p = to_annotation_page(t, CANVAS, "https://example.org/annotations/item1/1/ocr_new")
    lines = {a["body"]["value"]: a["body"].get("language") for a in p["items"] if a.get("textGranularity") == "line"}
    words = [a["body"].get("language") for a in p["items"] if a.get("textGranularity") == "word"]
    footnote = next(ln for ln in t.lines if ln.id == "l7")
    assert lines[t.text_of(footnote)] == "la" and lines["12 THE BOTANIST"] == "en"
    assert words[3:6] == ["en", "de", "en"]                         # l0 has three words, then l1's
    assert not any("language" in a["body"] for a in p["items"] if a["motivation"] == "classifying")


@pytest.mark.network
def test_the_page_is_valid_iiif():
    jsonschema = pytest.importorskip("jsonschema")
    with urllib.request.urlopen(SCHEMA_URL, timeout=30) as r:
        data = r.read()
    assert hashlib.sha256(data).hexdigest() == SCHEMA_SHA256
    jsonschema.validate(page(), json.loads(data))


def test_an_annotation_page_reads_back_as_written():
    import json

    from linecaster.formats.iiif import from_annotation_page
    from linecaster.testing import sample_transcription
    from linecaster.testing.scripts import script_page

    for t in (sample_transcription(), script_page("arabic")):
        page = to_annotation_page(t, "https://library.test/canvas/1", "https://library.test/anno/1")
        back = from_annotation_page(json.dumps(page))
        assert [back.text_of(ln) for ln in back.ordered_lines()] == [
            t.text_of(ln) for ln in t.ordered_lines() if ln.reading is not None]
        assert to_annotation_page(back, "https://library.test/canvas/1", "https://library.test/anno/1") == page
    assert back.language("r1l0") == "ar" and back.region_of(back.lines[2]) == "r1"


def test_a_foreign_annotation_page_with_selectors_percent_boxes_and_languages():
    from linecaster.formats.iiif import from_annotation_page

    canvas = "https://example.org/iiif/canvas/p1"
    person = {"creator": {"id": "https://example.org/people/1", "type": "Person", "name": "Transcriber"}}

    def anno(n, motivation, body, target, **extra):
        return {"id": f"https://example.org/anno/{n}", "type": "Annotation", "motivation": motivation, "body": body,
                "target": target, **person, **extra}

    page = {"id": "https://example.org/anno", "type": "AnnotationPage", "items": [
        anno(0, "classifying", {"type": "TextualBody", "value": "paragraph"}, f"{canvas}#xywh=percent:10,10,80,40"),
        anno(1, "supplementing", {"type": "TextualBody", "value": "The ship sailed", "language": "en"},
             {"type": "SpecificResource", "source": {"id": canvas, "type": "Canvas"},
              "selector": {"type": "FragmentSelector", "value": "xywh=110,120,700,40"}}, textGranularity="line"),
        anno(2, "transcribing", [{"type": "TextualBody", "value": "Ἐν ἀρχῇ", "language": "grc"}],
             {"type": "SpecificResource", "source": canvas,
              "selector": {"type": "SvgSelector", "value": "<svg><polygon points='110,200 500,200 500,240 110,240'/>"
                                                            "</svg>"}}, textGranularity="line"),
        anno(3, "supplementing", {"type": "TextualBody", "value": "ship", "language": "en"},
             f"{canvas}#xywh=200,120,100,40", textGranularity="word"),
        anno(4, "editing", {"type": "TextualBody", "value": "The ship sailed.", "purpose": "corrected"},
             "https://example.org/anno/1"),
        anno(5, "commenting", {"type": "TextualBody", "value": "a note on the scan"}, canvas),
    ]}
    t = from_annotation_page(page, image_width=1000, image_height=1000)
    assert [t.text_of(ln) for ln in t.ordered_lines()] == ["The ship sailed", "Ἐν ἀρχῇ"]
    assert t.regions[0].box == [100.0, 100.0, 800.0, 400.0] and t.role("r0") == "paragraph"
    assert [t.region_of(ln) for ln in t.lines] == ["r0", "r0"]
    assert t.lines[1].polygon == [[110.0, 200.0], [500.0, 200.0], [500.0, 240.0], [110.0, 240.0]]
    assert (t.language("l0"), t.language("l1"), t.language("")) == ("en", "grc", None)
    assert [w.text for w in t.lines[0].reading.words] == ["ship"]
    assert [(e.target, e.kind, e.text) for e in t.edits] == [("l0", "corrected", "The ship sailed.")]
    assert {a.kind for a in t.annotators} == {"human"} and t.annotators[0].name == "Transcriber"
