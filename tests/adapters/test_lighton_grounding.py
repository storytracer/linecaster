"""LightOnOCR-3's grounding mode (adapter ``lighton-ocr-3-grounding``, presets ``lightonocr-3-*-grounding``): the card's
grounding call, and fixed completions parsed into labelled regions: labels, order, boxes, continuations, the furniture
split, figure descriptions kept out of every text, and truncated, malformed and placeholder-less output."""
from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from linecaster.adapters import chat_model
from linecaster.adapters.lighton_grounding import ground, place

PRESETS = ("lightonocr-3-0.8b-grounding", "lightonocr-3-4b-grounding")

#: a book page as the model answers in grounding mode (the card's format)
PAGE = """![header](100,30,800,60)
THE HISTORY OF YACHTING.

![page_number](880,30,920,60)
143

![title](100,90,900,130)
## CHAPTER IX.

![text](100,140,900,400)
The *America* was built in 1851 by
George Steers, and sailed for England.

![aside_text](20,150,90,300)
Built 1851.

![image](100,420,900,700)
A schooner under full sail.

![caption](100,705,900,720)
The America off Cowes.

![chart](100,725,900,800)
<table><tr><th>Year</th><th>Races</th></tr><tr><td>1851</td><td>1</td></tr></table>

![list](100,805,900,830)
- the Cup

![formula](100,835,900,850)
$$v = s / t$$

![text+](100,860,900,940)
She won the cup at Cowes.

![page_number](480,960,520,980)
- 143 -
"""


def image(w: int = 200, h: int = 300) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.parametrize("ref", PRESETS)
def test_the_request_is_the_cards_grounding_call(ref):
    """The image, then the text part ``grounding``; the transcription preset's thumbnail and sampling."""
    a = chat_model(ref)
    body = a.request(image(3000, 4000))
    image_part, text_part = body["messages"][0]["content"]
    assert image_part["type"] == "image_url" and text_part == {"type": "text", "text": "grounding"}
    png = Image.open(io.BytesIO(base64.b64decode(image_part["image_url"]["url"].split(",", 1)[1])))
    assert max(png.size) == 2048
    assert (body["max_tokens"], body["temperature"], body["top_p"]) == (4096, 0.2, 0.9)
    assert a.settings()["prompt"] == "grounding" and a.settings()["mode"] == "grounding"
    transcription = chat_model(ref.removesuffix("-grounding"))
    assert transcription.adapter == "lighton-ocr-3" and transcription.revision == a.revision
    assert transcription.serve_args == a.serve_args and transcription.repair_caps == a.repair_caps
    assert chat_model("lightonai/LightOnOCR-3-0.8B").adapter == "lighton-ocr-3"      # the model's id: transcription


def test_blocks_become_labelled_regions_in_the_order_emitted():
    t = ground(PAGE, "stop")
    got = [(r.id, r.label, r.raw_label, r.reading_order) for r in t.regions]
    assert got == [("header_0", "page_header", "header", 0), ("page_number_1", "page_header", "page_number", 1),
                   ("title_2", "section_header", "title", 2), ("text_3", "text", "text", 3),
                   ("aside_text_4", "text", "aside_text", 4), ("image_5", "picture", "image", 5),
                   ("caption_6", "caption", "caption", 6), ("chart_7", "chart", "chart", 7),
                   ("list_8", "list_item", "list", 8), ("formula_9", "formula", "formula", 9),
                   ("text_10", "text", "text", 10), ("page_number_11", "page_footer", "page_number", 11)]
    r = {x.id: x for x in t.regions}
    assert r["title_2"].heading_level == 2 and [ln.text for ln in t.lines if ln.region_id == "title_2"] == ["CHAPTER IX."]
    assert r["text_10"].extra["continuation"] and r["text_10"].extra["continues"] == "text_3"
    assert r["text_10"].extra["label"] == "text+" and r["text_3"].extra["box_1000"] == [100, 140, 900, 400]
    assert r["formula_9"].extra["formula"] == "v = s / t"
    assert [ln.text for ln in t.lines if ln.region_id == "text_3"] == ["The *America* was built in 1851 by",
                                                                      "George Steers, and sailed for England."]
    g = t.extra["grounding"]
    assert (g["blocks"], g["generated"], g["unknown"], g["malformed"], g["missing"], g["truncated"]) == (
        12, 2, [], [], False, False)
    assert t.extra["raw"] == PAGE


def test_boxes_are_scaled_from_0_1000_to_the_page_image_once():
    t = place(ground(PAGE, "stop"), 2000, 3000)
    header = t.regions[0]
    assert header.bbox == [200.0, 90.0, 1400.0, 90.0] and header.polygon[2] == [1600.0, 180.0]
    a, b = [ln for ln in t.lines if ln.region_id == "text_3"]          # the block's box split into its rows
    assert a.bbox == [200.0, 420.0, 1600.0, 390.0] and b.bbox == [200.0, 810.0, 1600.0, 390.0]
    assert a.extra == {"box": "estimated"}
    assert (t.source.image_width, t.source.image_height) == (2000, 3000)
    assert t.extra["grounding"]["coordinates"] == "page"
    assert place(t, 4000, 6000).regions[0].bbox == [200.0, 90.0, 1400.0, 90.0]     # placed once


def test_the_full_text_keeps_the_furniture_and_the_body_texts_leave_it_out():
    from linecaster.engines import UnicodeRecompositionEngine
    from linecaster.formats.docling import build_docling, to_text
    from linecaster.text.variants import variants

    t = place(ground(PAGE, "stop"), 2000, 3000)
    assert t.text.startswith("THE HISTORY OF YACHTING.\n143\nCHAPTER IX.") and t.text.endswith("- 143 -")
    doc = build_docling(t, width=2000, height=3000)
    body, full = to_text(doc, furniture=False), to_text(doc, furniture=True)
    assert "THE HISTORY" in full and "THE HISTORY" not in body and "143" not in body
    assert "Built 1851." in body and "She won the cup" in body                # marginalia are body text
    (recomposed,) = UnicodeRecompositionEngine()([t])
    v = variants([recomposed])
    assert "THE HISTORY" in v["verbatim_txt"] and "THE HISTORY" not in v["readable_txt"]
    assert "143" not in v["readable_txt"] and "She won the cup" in v["readable_txt"]


def test_what_the_model_writes_about_figures_is_kept_but_in_no_text():
    """An image's description and a chart's data are the model's, not printed: stored on the region, no lines."""
    from linecaster.formats.docling import build_docling, to_markdown, to_text

    t = place(ground(PAGE, "stop"), 2000, 3000)
    r = {x.id: x for x in t.regions}
    assert r["image_5"].extra["generated"] == {"kind": "description", "content": "A schooner under full sail."}
    assert r["chart_7"].extra["generated"]["kind"] == "data" and "<table>" in r["chart_7"].extra["generated"]["content"]
    assert r["image_5"].extra["printed"] is False and not [ln for ln in t.lines if ln.region_id in ("image_5", "chart_7")]
    doc = build_docling(t, width=2000, height=3000)
    for text in (t.text, to_text(doc, furniture=True), to_markdown(doc, furniture=True)):
        assert "schooner under full sail" not in text and "Races" not in text
    assert "The America off Cowes." in t.text                                 # the printed caption is text


def test_unknown_labels_are_kept_and_counted():
    t = ground("![marginalia](0,0,100,100)\nA note.\n![text](0,100,1000,900)\nBody.", "stop")
    assert [(r.label, r.raw_label) for r in t.regions] == [("text", "marginalia"), ("text", "text")]
    assert t.extra["grounding"]["unknown"] == ["marginalia"] and "A note." in t.text


def test_a_completion_cut_off_marks_its_last_block_truncated():
    t = ground("![text](0,0,1000,500)\nA full block.\n![table](0,500,1000,1000)\n<table><tr><td>1</td>", "length")
    assert t.regions[-1].extra["truncated"] and "truncated" not in t.regions[0].extra
    assert t.extra["grounding"]["truncated"] and t.extra["finish_reason"] == "length"
    assert t.text.endswith("<table><tr><td>1</td>")


def test_malformed_placeholders_text_before_any_and_no_placeholder_at_all():
    """Nothing is dropped or guessed: a malformed placeholder's content and text before the first placeholder become
    lines without a region; a completion without any placeholder is all such lines, recorded as ``missing``."""
    raw = "Stray line.\n![text](0,0,1000)\nMalformed box.\n![text](0,0,1000,1000)\nGood.\n![tex"
    t = ground(raw, "length")
    assert [r.id for r in t.regions] == ["text_1"]
    assert [(ln.text, ln.region_id) for ln in t.lines] == [("Stray line.", None), ("Malformed box.", None),
                                                          ("Good.", "text_1")]
    g = t.extra["grounding"]
    assert g["malformed"] == ["![text](0,0,1000)", "![tex"] and g["unplaced"] == 1 and g["blocks"] == 1
    assert not g["truncated"]                       # the cut-off part is the malformed placeholder, not a block
    plain = ground("Just text,\nno placeholders.", "stop")
    assert plain.regions == [] and plain.text == "Just text,\nno placeholders." and plain.extra["grounding"]["missing"]


def test_placeholders_out_of_range_or_reversed_are_malformed():
    for box in ("0,0,1001,10", "500,0,400,10", "a,b,c,d", "1,2,3,4,5"):
        t = ground(f"![text]({box})\nX", "stop")
        assert t.regions == [] and t.extra["grounding"]["malformed"] == [f"![text]({box})"], box
