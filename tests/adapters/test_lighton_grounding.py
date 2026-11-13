"""LightOnOCR-3's grounding mode (adapter ``lighton-ocr-3-grounding``, presets ``lightonocr-3-*-grounding``): the card's
grounding call, and fixed completions parsed into labelled regions: labels and content roles, order, boxes,
continuations, the furniture split, figure descriptions kept out of every text, and truncated, malformed and
placeholder-less output."""
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


def texts(t, region_id):
    return [t.text_of(ln) for ln in t.lines_of(region_id)]


def test_blocks_become_labelled_regions_in_the_order_emitted():
    """The model's label verbatim, its content role and the Docling label of that role; a page number's Docling
    label by its position on the page (top half: ``page_header``)."""
    t = ground(PAGE, "stop")
    got = [(r.id, t.label(r.id), r.label, t.role(r.id), rank) for rank, r in enumerate(t.ordered_regions())]
    assert got == [("header_0", "page_header", "header", "header", 0),
                   ("page_number_1", "page_header", "page_number", "page_number", 1),
                   ("title_2", "section_header", "title", "heading", 2), ("text_3", "text", "text", "paragraph", 3),
                   ("aside_text_4", "text", "aside_text", "marginalia", 4),
                   ("image_5", "picture", "image", "picture", 5), ("caption_6", "caption", "caption", "caption", 6),
                   ("chart_7", "chart", "chart", "chart", 7), ("list_8", "list_item", "list", "list_item", 8),
                   ("formula_9", "formula", "formula", "formula", 9), ("text_10", "text", "text", "paragraph", 10),
                   ("page_number_11", "page_footer", "page_number", "page_number", 11)]
    assert [r.id for r in t.regions] == [x[0] for x in got]
    r = {x.id: x for x in t.regions}
    assert t.heading_level("title_2") == 2 and texts(t, "title_2") == ["CHAPTER IX."]
    assert r["text_10"].lighton__continuation and t.link("text_10", "continues") == "text_3"
    assert r["text_10"].label == "text" and r["text_3"].lighton__box_1000 == [100, 140, 900, 400]
    assert t.formula("formula_9").latex == "v = s / t"
    assert texts(t, "text_3") == ["The *America* was built in 1851 by", "George Steers, and sailed for England."]
    g = t.lighton__grounding
    assert (g["blocks"], g["generated"], g["unknown"], g["malformed"], g["missing"], g["truncated"]) == (
        12, 2, [], [], False, False)
    assert t.outputs[0].content == PAGE and t.outputs[0].finish_reason == "stop"
    every = [*t.regions, *t.lines, *t.formulas, *t.descriptions, *t.links]
    assert all(x.annotator == 0 and x.output == 0 for x in every)          # parsed from the completion


def test_boxes_are_scaled_from_0_1000_to_the_page_image_once():
    t = place(ground(PAGE, "stop"), 2000, 3000)
    header = t.regions[0]
    assert header.box == [200.0, 90.0, 1400.0, 90.0] and header.polygon[2] == [1600.0, 180.0]
    a, b = t.lines_of("text_3")                                          # the block's box split into its rows
    assert a.box == [200.0, 420.0, 1600.0, 390.0] and b.box == [200.0, 810.0, 1600.0, 390.0]
    assert a.extensions == {"lighton__estimated": True}
    assert (t.source.image_width, t.source.image_height) == (2000, 3000)
    assert t.lighton__grounding["coordinates"] == "page"
    assert place(t, 4000, 6000).regions[0].box == [200.0, 90.0, 1400.0, 90.0]      # placed once
    assert t.label("page_number_11") == "page_footer" and t.label("page_number_1") == "page_header"


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
    """An image's description and a chart's data are the model's, not printed: descriptions of the region, no
    lines."""
    from linecaster.formats.docling import build_docling, to_markdown, to_text

    t = place(ground(PAGE, "stop"), 2000, 3000)
    (image,), (chart,) = t.descriptions_of("image_5"), t.descriptions_of("chart_7")
    assert (image.kind, image.text) == ("description", "A schooner under full sail.")
    assert chart.kind == "data" and "<table>" in chart.text and chart.format == "html"
    assert not t.lines_of("image_5") and not t.lines_of("chart_7")
    doc = build_docling(t, width=2000, height=3000)
    for text in (t.text, to_text(doc, furniture=True), to_markdown(doc, furniture=True)):
        assert "schooner under full sail" not in text and "Races" not in text
    assert "The America off Cowes." in t.text                                 # the printed caption is text


def test_unknown_labels_are_kept_and_counted():
    t = ground("![marginalia](0,0,100,100)\nA note.\n![text](0,100,1000,900)\nBody.", "stop")
    assert [(t.label(r.id), r.label, t.role(r.id)) for r in t.regions] == [("text", "marginalia", "other"),
                                                                           ("text", "text", "paragraph")]
    assert t.lighton__grounding["unknown"] == ["marginalia"] and "A note." in t.text


def test_a_completion_cut_off_marks_its_last_block_truncated():
    t = ground("![text](0,0,1000,500)\nA full block.\n![table](0,500,1000,1000)\n<table><tr><td>1</td>", "length")
    assert t.regions[-1].lighton__truncated and "lighton__truncated" not in t.regions[0].extensions
    assert t.lighton__grounding["truncated"] and t.outputs[0].finish_reason == "length"
    assert t.text.endswith("<table><tr><td>1</td>")


def test_malformed_placeholders_text_before_any_and_no_placeholder_at_all():
    """Nothing is dropped or guessed: a malformed placeholder's content and text before the first placeholder become
    lines without a region; a completion without any placeholder is all such lines, recorded as ``missing``."""
    raw = "Stray line.\n![text](0,0,1000)\nMalformed box.\n![text](0,0,1000,1000)\nGood.\n![tex"
    t = ground(raw, "length")
    assert [r.id for r in t.regions] == ["text_1"]
    assert [(t.text_of(ln), ln.region) for ln in t.lines] == [("Stray line.", None), ("Malformed box.", None),
                                                             ("Good.", "text_1")]
    g = t.lighton__grounding
    assert g["malformed"] == ["![text](0,0,1000)", "![tex"] and g["unplaced"] == 1 and g["blocks"] == 1
    assert not g["truncated"]                       # the cut-off part is the malformed placeholder, not a block
    plain = ground("Just text,\nno placeholders.", "stop")
    assert plain.regions == [] and plain.text == "Just text,\nno placeholders." and plain.lighton__grounding["missing"]


def test_placeholders_out_of_range_or_reversed_are_malformed():
    for box in ("0,0,1001,10", "500,0,400,10", "a,b,c,d", "1,2,3,4,5"):
        t = ground(f"![text]({box})\nX", "stop")
        assert t.regions == [] and t.lighton__grounding["malformed"] == [f"![text]({box})"], box


#: a page as the model writes it in practice: each block's first content line after its placeholder, on the same
#: line; a list block's items on the lines after it (the run report of 141,461 completions: 97.5 % on the same line)
INLINE = """![header](100,30,800,60) A STUDY OF SUCCESS.
![page_number](880,30,920,60) 249
![title](349,206,594,227) # CHAPTER I.
![text](63,246,880,385) THAT was a terrible night, and the
storm went on until the morning.
![list](63,400,880,500)
- the first
- the second
![image](100,520,900,700) A ship in a storm.
![text+](63,720,880,900) It ended at dawn.
"""


def test_content_on_the_placeholders_line_is_the_blocks_first_line():
    t = ground(INLINE, "stop")
    assert [(r.id, t.label(r.id)) for r in t.regions] == [
        ("header_0", "page_header"), ("page_number_1", "page_header"), ("title_2", "section_header"),
        ("text_3", "text"), ("list_4", "list_item"), ("image_5", "picture"), ("text_6", "text")]
    by = {r.id: texts(t, r.id) for r in t.regions}
    assert by["header_0"] == ["A STUDY OF SUCCESS."] and by["page_number_1"] == ["249"]
    assert by["title_2"] == ["CHAPTER I."] and t.heading_level("title_2") == 1 and t.role("title_2") == "heading"
    assert by["text_3"] == ["THAT was a terrible night, and the", "storm went on until the morning."]
    assert by["list_4"] == ["- the first", "- the second"] and by["image_5"] == []
    assert t.descriptions_of("image_5")[0].text == "A ship in a storm."
    assert t.link("text_6", "continues") == "text_3"
    assert t.text.startswith("A STUDY OF SUCCESS.\n249\nCHAPTER I.\nTHAT was") and "A ship" not in t.text
    g = t.lighton__grounding
    assert (g["blocks"], g["malformed"], g["generated"]) == (7, [], 1)


def test_a_malformed_placeholder_keeps_the_text_after_it():
    t = ground("![text](0,0,1000) Broken box, kept.\nNext line.\n![image](image_1.png)\n"
               "![text](0,500,1000,1000) Good.", "stop")
    assert [(t.text_of(ln), ln.region) for ln in t.lines] == [("Broken box, kept.", None), ("Next line.", None),
                                                             ("Good.", "text_2")]
    assert t.lighton__grounding["malformed"] == ["![text](0,0,1000) Broken box, kept.", "![image](image_1.png)"]


def test_records_written_by_0_7_3_are_parsed_again_from_their_raw_completion():
    """0.7.3 took a placeholder only alone on its line: such a record (upgraded to page/3) has its raw completion and
    no text."""
    from linecaster.adapters.lighton_grounding import reground
    from linecaster.data.upgrade import upgrade_transcription

    old = upgrade_transcription({"steps": [{"step": "recognition", "name": "m"}],
                                 "extra": {"raw": INLINE, "finish_reason": "stop",
                                           "passes": [{"raw": INLINE, "finish_reason": "stop"}],
                                           "grounding": {"blocks": 1, "malformed": ["..."]}}})
    assert old.text == "" and old.outputs[0].content == INLINE
    new = reground(old, 1000, 2000)
    assert new.text.startswith("A STUDY OF SUCCESS.") and len(new.regions) == 7
    assert new.regions[3].box == [63.0, 492.0, 817.0, 278.0]            # placed on the 1000 x 2000 page
    assert new.annotators == old.annotators and new.outputs == old.outputs
    assert new.lighton__grounding["malformed"] == [] and new.lighton__grounding["coordinates"] == "page"
    assert "page2__grounding" not in new.extensions and all(r.annotator == 0 for r in new.regions)
