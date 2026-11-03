"""The SmolDocling spec: request, serve flags and DocTags parse as the BHL board's driver and harness ran it."""
from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from linecaster.blocks.serve import ServeChatModel
from linecaster.models import chat_model
from linecaster.models.smoldocling import PROMPT, SmolDocling, to_markdown

MODEL = "ds4sd/SmolDocling-256M-preview"
DOCTAGS = ("<doctag><page_header><loc_224><loc_42><loc_272><loc_50>APPENDIX</page_header>"
           "<page_header><loc_431><loc_44><loc_447><loc_50>205</page_header>"
           "<text><loc_43><loc_61><loc_447><loc_90>A female Orphean Warbler was shot.</text>"
           "<picture><loc_40><loc_100><loc_400><loc_300></picture></doctag><end_of_utterance>")


def image(w: int, h: int, fmt: str = "WEBP") -> bytes:
    buf = io.BytesIO()
    Image.new("L", (w, h), 200).save(buf, format=fmt)
    return buf.getvalue()


def completion(content, finish="stop"):
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 300}}


@pytest.mark.parametrize("size,expected", [((3000, 4000), (1536, 2048)), ((800, 600), (800, 600))])
def test_request_is_image_then_prompt_jpeg_downscaled_only(size, expected):
    b = chat_model(MODEL).request(image(*size))
    image_part, text_part = b["messages"][0]["content"]
    assert text_part == {"type": "text", "text": "Convert this page to docling."} and PROMPT == text_part["text"]
    url = image_part["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    im = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert im.format == "JPEG" and im.mode == "RGB" and im.size == expected
    assert (b["temperature"], b["max_tokens"], b["skip_special_tokens"]) == (0.0, 6144, False)
    assert set(b) == {"model", "messages", "temperature", "max_tokens", "skip_special_tokens"}


def test_serve_args_match_the_board_driver():
    spec = SmolDocling()
    args = spec.vllm_args(0.8)
    assert args[:2] == ["--revision", "ce51f56c4ebe36e0b1c3a55f67b261ba22a50bf8"]
    i = args.index("--max-model-len")
    assert args[i + 1] == "8192" and spec.sampling["max_tokens"] + 1600 <= 8192
    assert "--no-enable-prefix-caching" in args and "--trust-remote-code" not in args
    assert args[args.index("--limit-mm-per-prompt") + 1] == '{"image": 1}'
    assert ServeChatModel(spec, port=8123).command()[:3] == ["vllm", "serve", MODEL]


def test_parse_keeps_doctags_verbatim_and_converts_as_the_harness():
    t = SmolDocling().parse(completion(DOCTAGS), backend="served x")
    assert t.extra["raw"] == DOCTAGS and t.text == DOCTAGS
    # furniture (running head, page number) kept, picture placeholder empty
    assert t.extra["markdown"] == "APPENDIX\n\n205\n\nA female Orphean Warbler was shot."
    assert to_markdown("  \n") == ""
    m = t.model[0]
    assert (m.name, m.revision, m.measurements["finish_reason"]) == (MODEL, SmolDocling.revision, "stop")


def test_parse_keeps_the_page_when_conversion_fails(monkeypatch):
    import linecaster.models.smoldocling as mod

    def boom(_):
        raise ValueError("bad doctags")

    monkeypatch.setattr(mod, "to_markdown", boom)
    t = SmolDocling().parse(completion("<doctag><text>x"))
    assert t.extra["raw"] == "<doctag><text>x" and t.extra["markdown"] is None
    assert t.extra["markdown_error"] == "ValueError: bad doctags"
