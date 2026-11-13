"""``PageRecognizer`` with a grounding preset, against a fake OpenAI-compatible server: the regions placed on the page
image at its full size, the blocks counted, and a page cut off at ``max_tokens`` repaired as in transcription mode."""
from __future__ import annotations

import io

from PIL import Image

from linecaster.backends import Chat
from linecaster.blocks.base.page import new_page_document, page_of
from linecaster.blocks.recognition.chat import PageRecognizer
from linecaster.testing import fake_chat_server
from linecaster.testing.chat import completion

PRESET = "lightonocr-3-0.8b-grounding@1"
FULL = ("![header](100,30,900,60)\nRUNNING HEAD\n\n![text](100,100,900,900)\nBody text.\n\n"
        "![image](100,910,500,990)\nA drawing.\n\n![page_number](480,960,520,990)\n7\n")


def image(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new("L", (w, h), 255).save(buf, format="PNG")
    return buf.getvalue()


def answer(body: dict) -> dict:
    """The first request stops at its cap inside a table; the repair (more tokens) finishes the page."""
    usage = {"prompt_tokens": 3000, "completion_tokens": 900}
    if body["max_tokens"] <= 4096:
        return completion("![text](100,100,900,500)\nBody.\n![table](100,500,900,900)\n<table><tr>", finish="length",
                          usage=usage)
    return completion(FULL, usage=usage)


def test_regions_are_placed_on_the_page_and_a_cut_off_page_is_repaired():
    with fake_chat_server(answer) as server:
        step = PageRecognizer(Chat(PRESET, server.url, max_window=2))
        (out,) = list(step.run(iter([new_page_document("p", image(1000, 2000))])))
    assert len(server.requests) == 2 and server.requests[0]["messages"][0]["content"][1]["text"] == "grounding"
    t = page_of(out).transcriptions["ocr_new"]
    (kept,) = [o for o in t.outputs if o.kept]
    assert kept.pass_ == 2 and kept.finish_reason == "stop"                 # the repair finished: kept
    assert all(x.output == t.outputs.index(kept) for x in [*t.regions, *t.lines])
    assert [(t.label(r.id), r.label) for r in t.regions] == [("page_header", "header"), ("text", "text"),
                                                            ("picture", "image"), ("page_footer", "page_number")]
    assert t.regions[1].box == [100.0, 200.0, 800.0, 1600.0]                 # 0-1000 -> the 1000 x 2000 page
    assert (t.source.image_width, t.source.image_height) == (1000, 2000)
    assert out.text == "RUNNING HEAD\nBody text.\n7"
    stats = {k: step.stats[k].total for k in ("grounding_blocks", "grounding_generated", "finish_length")}
    assert stats == {"grounding_blocks": 4, "grounding_generated": 1, "finish_length": 1}


def test_a_page_without_placeholders_is_counted_and_kept_as_text():
    with fake_chat_server(lambda body: completion("Only text.")) as server:
        step = PageRecognizer(Chat(PRESET, server.url, max_window=2))
        (out,) = list(step.run(iter([new_page_document("p", image(100, 200))])))
    t = page_of(out).transcriptions["ocr_new"]
    assert t.regions == [] and out.text == "Only text." and step.stats["grounding_missing"].total == 1
