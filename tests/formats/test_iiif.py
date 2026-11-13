"""The IIIF annotation page of a transcription: its annotations, and validity against the IIIF Presentation 3 JSON
Schema of the IIIF presentation validator, fetched at a pinned commit (the file states no licence, so it is not
copied into this repository)."""
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


@pytest.mark.network
def test_the_page_is_valid_iiif():
    jsonschema = pytest.importorskip("jsonschema")
    with urllib.request.urlopen(SCHEMA_URL, timeout=30) as r:
        data = r.read()
    assert hashlib.sha256(data).hexdigest() == SCHEMA_SHA256
    jsonschema.validate(page(), json.loads(data))
