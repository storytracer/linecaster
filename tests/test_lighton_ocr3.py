"""The LightOnOCR-3 specs (4B and 0.8B): request body, serve flags and parse, against the board driver."""
from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from linecaster.blocks.serve import ServeChatModel
from linecaster.models import chat_model
from linecaster.transcription.model import Transcription

REVISIONS = {"lightonai/LightOnOCR-3-4B": "b71010f095dc3735de7ee6b9969bff8f8f50b39a",
             "lightonai/LightOnOCR-3-0.8B": "36d8636925327c671bd8e479c517a004f7566bd9"}


def image(w: int, h: int, fmt: str = "WEBP", mode: str = "L") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), 200).save(buf, format=fmt)
    return buf.getvalue()


def sent_png(body: dict) -> bytes:
    url = body["messages"][0]["content"][0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    return base64.b64decode(url.split(",", 1)[1])


def driver_encode_png(data: bytes) -> bytes:
    """The board driver's ``encode_png``, verbatim apart from the input handling."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((2048, 2048))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.parametrize("model", list(REVISIONS))
def test_registry_and_revisions(model):
    spec = chat_model(model)
    assert spec.adapter == "lighton-ocr-3" and spec.preset == {"lightonai/LightOnOCR-3-4B": "lightonocr-3-4b@1",
                                                                "lightonai/LightOnOCR-3-0.8B": "lightonocr-3-0.8b@1"}[model]
    assert spec.model == model and spec.revision == REVISIONS[model]


@pytest.mark.parametrize("size, expected", [
    ((3000, 4000), (1536, 2048)),    # portrait, downscaled
    ((4000, 3000), (2048, 1536)),    # landscape
    ((700, 1000), (700, 1000)),      # smaller than 2048: NOT upscaled (thumbnail)
    ((2048, 1000), (2048, 1000)),    # already at the target: untouched
])
def test_request_thumbnails_to_2048(size, expected):
    im = Image.open(io.BytesIO(sent_png(chat_model("lightonocr-3-4b").request(image(*size)))))
    assert im.format == "PNG" and im.mode == "RGB" and im.size == expected


@pytest.mark.parametrize("fmt, mode", [("JPEG", "RGB"), ("WEBP", "L"), ("PNG", "RGBA")])
def test_request_image_bytes_equal_the_driver(fmt, mode):
    data = image(2600, 3900, fmt, mode)
    assert sent_png(chat_model("lightonocr-3-0.8b").request(data)) == driver_encode_png(data)


@pytest.mark.parametrize("model", list(REVISIONS))
def test_request_body_is_the_drivers(model):
    body = chat_model(model).request(image(800, 1200, "JPEG"))
    assert set(body) == {"model", "messages", "max_tokens", "temperature", "top_p", "chat_template_kwargs"}
    assert body["model"] == model
    assert len(body["messages"]) == 1 and body["messages"][0]["role"] == "user"
    content = body["messages"][0]["content"]
    assert len(content) == 1 and content[0]["type"] == "image_url"      # image only, no text part
    assert (body["max_tokens"], body["temperature"], body["top_p"]) == (4096, 0.2, 0.9)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.parametrize("model", list(REVISIONS))
def test_serve_args_match_the_board_driver(model):
    args = chat_model(model).vllm_args(0.8)
    assert args[:2] == ["--revision", REVISIONS[model]]
    for flag in (["--max-model-len", "16384"],
                 ["--default-chat-template-kwargs", '{"enable_thinking": false}'],
                 ["--limit-mm-per-prompt", '{"image": 1, "video": 0}'],
                 ["--mm-processor-cache-gb", "0"], ["--gpu-memory-utilization", "0.8"]):
        i = args.index(flag[0])
        assert args[i:i + 2] == flag
    assert "--no-enable-prefix-caching" in args and "--trust-remote-code" not in args
    assert "--served-model-name" not in args
    cmd = ServeChatModel(chat_model(model), port=8123).command()
    assert cmd[:3] == ["vllm", "serve", model]


def test_parse_keeps_the_completion_verbatim():
    raw = "\n# THE HAWFINCH\n\nnest itself  \n"
    body = {"choices": [{"message": {"role": "assistant", "content": raw}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3100, "completion_tokens": 9}}
    t = chat_model("lightonocr-3-0.8b").parse(body, backend="served x")
    assert t.extra["raw"] == raw and t.text == raw                       # not even a strip
    m = t.model[0]
    assert (m.name, m.revision) == ("lightonai/LightOnOCR-3-0.8B", REVISIONS["lightonai/LightOnOCR-3-0.8B"])
    assert m.measurements == {"prompt_tokens": 3100, "completion_tokens": 9, "finish_reason": "stop"}
    assert m.settings["image"]["longest_side_px"] == 2048 and m.settings["prompt"] is None
    assert m.settings["chat_template_kwargs"] == {"enable_thinking": False}
    assert Transcription.model_validate_json(t.model_dump_json()) == t
