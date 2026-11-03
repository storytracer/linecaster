"""Qwen3.5-9B spec: request body, image budget, serve flags, as the BHL board ran it (greedy + card penalties)."""
from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from linecaster.blocks.serve import ServeChatModel
from linecaster.models import chat_model
from linecaster.models.qwen35 import unwrap_fence

PROMPT = chat_model("qwen3.5-9b").prompt
MAX_PIXELS = 2048 * 1024          # the driver's VISUAL_TOKEN_BUDGET x 1024 px

MODEL = "Qwen/Qwen3.5-9B"


def image(w: int, h: int, fmt: str = "WEBP", mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), 200 if mode == "L" else (200, 190, 180)).save(buf, format=fmt)
    return buf.getvalue()


def sent_image(body: dict) -> Image.Image:
    url = body["messages"][0]["content"][0]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))


def test_request_matches_the_board_row():
    b = chat_model(MODEL).request(image(800, 1200, "PNG", "L"))
    assert b["model"] == MODEL
    image_part, text_part = b["messages"][0]["content"]
    assert image_part["type"] == "image_url" and text_part == {"type": "text", "text": PROMPT}
    assert PROMPT == "Transcribe all of the text in this image."
    assert (b["temperature"], b["presence_penalty"], b["repetition_penalty"], b["max_tokens"]) == (0.0, 1.5, 1.0, 8192)
    assert b["chat_template_kwargs"] == {"enable_thinking": False}
    assert set(b) == {"model", "messages", "temperature", "presence_penalty", "repetition_penalty", "max_tokens",
                      "chat_template_kwargs"}          # greedy: no top_p/top_k/min_p, no seed


@pytest.mark.parametrize("size, expected", [
    ((2000, 3000), (1182, 1773)),     # 6 Mpx -> area 2048 * 1024, int-truncated
    ((1000, 1500), (1000, 1500)),     # under the budget: untouched, never upscaled
    ((1024, 2048), (1024, 2048)),     # exactly the budget: untouched
])
def test_image_is_area_capped_jpeg(size, expected):
    im = sent_image(chat_model("qwen3.5-9b").request(image(*size)))
    assert im.format == "JPEG" and im.mode == "RGB" and im.size == expected
    assert im.size[0] * im.size[1] <= MAX_PIXELS


def test_serve_args_match_the_board_driver():
    spec = chat_model("qwen3.5-9b")
    cmd = ServeChatModel(spec, port=8000, gpu_memory_utilization=0.9).command()
    assert cmd[:3] == ["vllm", "serve", MODEL]
    args = spec.vllm_args(0.9)
    assert args[:2] == ["--revision", "c202236235762e1c871ad0ccb60c8ee5ba337b9a"]
    for flag, value in (("--max-model-len", "16384"), ("--max-num-batched-tokens", "16384"),
                        ("--mm-processor-cache-gb", "0"), ("--limit-mm-per-prompt", '{"image": 1, "video": 0}'),
                        ("--gpu-memory-utilization", "0.9")):
        assert args[args.index(flag) + 1] == value
    assert "--no-enable-prefix-caching" in args
    assert "--reasoning-parser" not in args and "--trust-remote-code" not in args


def test_prompt_hash_is_recorded():
    import hashlib

    s = chat_model("qwen3.5-9b").settings()
    assert s["prompt_variant"] == "neutral" and s["prompt_sha8"] == hashlib.sha256(PROMPT.encode()).hexdigest()[:8]


def test_parse_keeps_raw_and_unwrap_fence_is_the_boards():
    raw = "```markdown\nTHE BIRDS\n\nof Ceylon.\n```"
    t = chat_model("qwen3.5-9b").parse({"choices": [{"message": {"content": raw}, "finish_reason": "stop"}], "usage": {}})
    assert t.extra["raw"] == raw and t.text == raw and t.model[0].name == MODEL
    assert unwrap_fence(raw) == "THE BIRDS\n\nof Ceylon."
    assert unwrap_fence("```\nplain\n```") == "plain"
    assert unwrap_fence("a ``` b ``` c") == "a ``` b ``` c"
    assert unwrap_fence("```x```\n\n```y```") == "```x```\n\n```y```"      # several fences: left alone
