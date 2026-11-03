"""The PaddleOCR-VL-1.6 spec: request, parse and serve flags as the BHL board's driver ran the model."""
from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from linecaster.blocks.serve import ServeChatModel
from linecaster.models import chat_model
from linecaster.models.paddleocr_vl import MAX_PIXELS, MIN_PIXELS, PaddleOCRVL16, smart_resize


def image(w: int, h: int, fmt: str = "JPEG", mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), 200 if mode == "L" else (200, 190, 180)).save(buf, format=fmt)
    return buf.getvalue()


def sent(body: dict) -> Image.Image:
    url = body["messages"][0]["content"][0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))


@pytest.mark.parametrize("w, h", [(2400, 3600), (3600, 2400), (300, 200), (1000, 1000), (812, 1176)])
def test_smart_resize_lands_on_the_28_grid_within_bounds(w, h):
    hb, wb = smart_resize(h, w)
    assert hb % 28 == 0 and wb % 28 == 0 and MIN_PIXELS <= hb * wb <= MAX_PIXELS


@pytest.mark.parametrize("size, expected", [
    ((2400, 3600), (812, 1204)),     # large page: shrunk (floor) to at most 1280 tiles
    ((300, 200), (392, 280)),          # tiny page: grown (ceil) to at least 130 tiles
    ((812, 1176), (812, 1176)),      # on the grid already: unresized
])
def test_request_matches_the_driver(size, expected):
    body = chat_model("PaddlePaddle/PaddleOCR-VL-1.6").request(image(*size, mode="L"))
    assert body["model"] == "PaddlePaddle/PaddleOCR-VL-1.6"
    assert body["messages"][0]["content"][1] == {"type": "text", "text": "OCR:"}
    assert (body["temperature"], body["max_tokens"]) == (0.0, 4096)
    assert set(body) == {"model", "messages", "temperature", "max_tokens"}
    im = sent(body)
    assert (im.format, im.mode, im.size) == ("PNG", "RGB", expected)


def test_serve_args_match_the_driver():
    cmd = ServeChatModel(PaddleOCRVL16(), port=8000, gpu_memory_utilization=0.8).command()
    assert cmd[:3] == ["vllm", "serve", "PaddlePaddle/PaddleOCR-VL-1.6"]
    args = cmd[7:]
    assert args[:2] == ["--revision", "66317acc4c9fc17bd154591ce650735cd2855f3e"]
    for flag in (["--max-model-len", "8192"], ["--max-num-batched-tokens", "16384"], ["--mm-processor-cache-gb", "0"],
                 ["--limit-mm-per-prompt", '{"image": 1}'], ["--gpu-memory-utilization", "0.8"]):
        i = args.index(flag[0])
        assert args[i:i + 2] == flag
    assert {"--trust-remote-code", "--enforce-eager", "--no-enable-prefix-caching"} <= set(args)


def test_parse_keeps_the_completion_verbatim():
    raw = "  12. Helix (Patula) rotundata, Müll.\nHab. Near Bristol.\n"
    t = PaddleOCRVL16().parse({"choices": [{"message": {"content": raw}, "finish_reason": "stop"}]})
    assert t.text == raw and t.model[0].settings["prompt"] == "OCR:"
