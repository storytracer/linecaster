"""Qianfan-OCR spec: request body (bytes as received), serve flags, as the BHL board ran it."""
from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from linecaster.adapters import chat_model
from linecaster.adapters.qianfan_ocr import sniff_mime
from linecaster.blocks.servers.serve import ServeChatModel

MODEL = "baidu/Qianfan-OCR"


def image(w: int, h: int, fmt: str, mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), 200 if mode in ("L", "1") else (200, 190, 180)).save(buf, format=fmt)
    return buf.getvalue()


@pytest.mark.parametrize("fmt, mode, mime", [("WEBP", "RGB", "image/webp"), ("JPEG", "L", "image/jpeg"),
                                             ("PNG", "1", "image/png"), ("TIFF", "RGB", "image/tiff")])
def test_request_sends_the_bytes_as_received(fmt, mode, mime):
    data = image(3000, 4500, fmt, mode)
    b = chat_model(MODEL).request(data)
    image_part, text_part = b["messages"][0]["content"]
    head, b64 = image_part["image_url"]["url"].split(",", 1)
    assert head == f"data:{mime};base64" and base64.b64decode(b64) == data       # no resize, no conversion
    assert text_part == {"type": "text", "text": "Parse this document to Markdown."}
    assert b["model"] == MODEL
    assert (b["temperature"], b["top_p"], b["max_tokens"]) == (0.0, 1.0, 8192)
    assert b["chat_template_kwargs"] == {"enable_thinking": False}
    assert set(b) == {"model", "messages", "temperature", "top_p", "max_tokens", "chat_template_kwargs"}


def test_unknown_image_bytes_raise_as_in_the_driver():
    with pytest.raises(ValueError, match="magic bytes"):
        sniff_mime(b"GIF89a....")


def test_serve_args_match_the_board_driver():
    spec = chat_model("qianfan-ocr")
    assert ServeChatModel(spec, port=8000).command()[:3] == ["vllm", "serve", MODEL]
    args = spec.vllm_args(0.85)
    assert args[:2] == ["--revision", "623bf5d20d446abdb36606aa4547cd0c18886fe5"]
    for flag, value in (("--max-model-len", "16384"), ("--limit-mm-per-prompt", '{"image": 1}'),
                        ("--mm-processor-cache-gb", "0"), ("--gpu-memory-utilization", "0.85")):
        assert args[args.index(flag) + 1] == value
    assert "--no-enable-prefix-caching" in args
    assert "--trust-remote-code" not in args and "--hf-overrides" not in args


def test_parse_keeps_raw_verbatim():
    raw = "\n# THE BIRDS\n\nof Ceylon.\n"
    t = chat_model("qianfan-ocr").parse({"choices": [{"message": {"content": raw}, "finish_reason": "length"}],
                            "usage": {"prompt_tokens": 3400, "completion_tokens": 8192}})
    assert t.extra["raw"] == raw and t.text == raw and t.extra["finish_reason"] == "length"
    assert t.model[0].revision == chat_model("qianfan-ocr").revision and t.model[0].measurements["completion_tokens"] == 8192
