"""The GLM-OCR spec: request, parse and serve flags as the BHL board's driver ran the model."""
from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from linecaster.adapters import chat_model
from linecaster.blocks.servers.serve import ChatModelServer


def image(w: int, h: int, fmt: str = "JPEG", mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), 200 if mode == "L" else (200, 190, 180)).save(buf, format=fmt)
    return buf.getvalue()


def sent(body: dict) -> Image.Image:
    url = body["messages"][0]["content"][0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))


@pytest.mark.parametrize("size, expected", [
    ((3000, 4500), (2534, 3801)),    # 13.5 MP > 9633792 px: scaled by sqrt, sides truncated
    ((2000, 3000), (2000, 3000)),    # below the ceiling: as it is (never upscaled)
])
def test_request_matches_the_driver(size, expected):
    body = chat_model("zai-org/GLM-OCR").request(image(*size, mode="L"))
    assert body["model"] == "zai-org/GLM-OCR"
    assert body["messages"][0]["content"][1] == {"type": "text", "text": "Text Recognition:"}
    assert (body["temperature"], body["top_p"], body["repetition_penalty"], body["max_tokens"]) == (0.01, 1e-05, 1.1, 8192)
    im = sent(body)
    assert (im.format, im.mode, im.size) == ("PNG", "RGB", expected)
    assert im.width * im.height <= 9633792


def test_serve_args_match_the_driver():
    cmd = ChatModelServer(chat_model("glm-ocr"), port=8000, gpu_memory_utilization=0.8).command()
    assert cmd[:3] == ["vllm", "serve", "zai-org/GLM-OCR"]
    args = cmd[7:]
    assert args[:2] == ["--revision", "ca5d8b3e287e52589e37c28385d9655ee4372f9d"]
    for flag in (["--max-model-len", "32768"], ["--mm-processor-cache-gb", "0"], ["--limit-mm-per-prompt", '{"image": 1}']):
        i = args.index(flag[0])
        assert args[i:i + 2] == flag
    assert "--no-enable-prefix-caching" in args and "--trust-remote-code" not in args


def test_parse_keeps_the_completion_verbatim():
    raw = "\n# PROCEEDINGS\n\nShell 6 mm. × 2·5 mm.\n"
    t = chat_model("glm-ocr").parse({"choices": [{"message": {"content": raw}, "finish_reason": "stop"}]})
    assert t.text == raw and chat_model("glm-ocr").parse({"choices": [{"message": {"content": None}}]}).text == ""
