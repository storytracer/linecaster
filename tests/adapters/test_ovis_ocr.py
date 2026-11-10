"""The OvisOCR2 and OvisOCR3 specs: request, parse and serve flags after the model card."""
from __future__ import annotations

import base64
import io
import math
import random

import pytest
from PIL import Image

from linecaster.adapters import chat_model
from linecaster.blocks.servers.serve import ChatModelServer

PROMPT = chat_model("ovisocr3").prompt

REVISIONS = {"ATH-MaaS/OvisOCR2": "65c619d374b55d4152e85150fc1b003700bc1f0c",
             "ATH-MaaS/OvisOCR3": "5f6ce6932efee9ec10c30746db55bd780214b7fd"}


FAST_ENCODING = {"WEBP": {"method": 0}, "PNG": {"compress_level": 1}}


def image(w: int, h: int, fmt: str = "WEBP", mode: str = "L") -> bytes:
    """A page of seeded noise; WebP and PNG are encoded at their fastest settings, which the request reads the same."""
    noise = Image.frombytes("L", (w, h), random.Random(0).randbytes(w * h))
    buf = io.BytesIO()
    noise.convert(mode).save(buf, format=fmt, **FAST_ENCODING.get(fmt, {}))
    return buf.getvalue()


def sent(body: dict) -> bytes:
    url = body["messages"][0]["content"][0]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    return base64.b64decode(url.split(",", 1)[1])


def reference_encode_jpeg(data: bytes) -> bytes:
    """The reference implementation's ``encode_jpeg``, verbatim apart from the input handling."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = img.size
    if w * h > 8294400:
        scale = math.sqrt(8294400 / (w * h))
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


@pytest.mark.parametrize("model", list(REVISIONS))
def test_registry_and_revisions(model):
    spec = chat_model(model)
    assert spec.adapter == "ovis-ocr" and spec.preset == {"ATH-MaaS/OvisOCR2": "ovisocr2@1",
                                                            "ATH-MaaS/OvisOCR3": "ovisocr3@1"}[model]
    assert spec.revision == REVISIONS[model]


def test_prompts():
    assert chat_model("ovisocr2").prompt == "\n" + PROMPT and chat_model("ovisocr3").prompt == PROMPT     # OvisOCR3: the repo's prompt file
    assert PROMPT.startswith("Extract all readable content from the image in natural human reading order")
    assert '<img src="images/bbox_{left}_{top}_{right}_{bottom}.jpg" />' in PROMPT


@pytest.mark.parametrize("model", list(REVISIONS))
def test_request_body_is_the_reference(model):
    spec = chat_model(model)
    body = spec.request(image(800, 1200, "JPEG", "RGB"))
    assert set(body) == {"model", "messages", "temperature", "max_tokens", "chat_template_kwargs"}
    assert body["model"] == model
    assert (body["temperature"], body["max_tokens"]) == (0.0, 16384)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    image_part, text_part = body["messages"][0]["content"]
    assert image_part["type"] == "image_url" and text_part == {"type": "text", "text": spec.prompt}


@pytest.mark.parametrize("size, expected", [
    ((3000, 4500), (2351, 3527)),    # 13.5 Mpx -> under 8,294,400 px, int() sides
    ((2000, 3000), (2000, 3000)),    # fits: not resized (but re-encoded)
    ((300, 400), (300, 400)),        # never upscaled
])
def test_request_downscales_to_max_pixels(size, expected):
    im = Image.open(io.BytesIO(sent(chat_model("ovisocr2").request(image(*size)))))
    assert (im.format, im.mode, im.size) == ("JPEG", "RGB", expected)
    assert im.size[0] * im.size[1] <= 8294400


@pytest.mark.parametrize("fmt, mode", [("JPEG", "RGB"), ("WEBP", "L"), ("PNG", "RGBA"), ("PNG", "L")])
def test_request_image_bytes_equal_the_reference(fmt, mode):
    data = image(2600, 3900, fmt, mode)
    assert sent(chat_model("ovisocr3").request(data)) == reference_encode_jpeg(data)


@pytest.mark.parametrize("model", list(REVISIONS))
def test_serve_args_match_the_card(model):
    cmd = ChatModelServer(chat_model(model), port=8000, gpu_memory_utilization=0.8).command()
    assert cmd[:3] == ["vllm", "serve", model]
    args = cmd[7:]
    for flag in (["--revision", REVISIONS[model]], ["--max-model-len", "32768"], ["--mm-processor-cache-gb", "0"],
                 ["--limit-mm-per-prompt", '{"image": 1}'],
                 ["--mm-processor-kwargs", '{"images_kwargs": {"min_pixels": 200704, "max_pixels": 8294400}}'],
                 ["--gpu-memory-utilization", "0.8"]):
        i = args.index(flag[0])
        assert args[i:i + 2] == flag
    assert "--no-enable-prefix-caching" in args
    assert "--trust-remote-code" not in args and "--served-model-name" not in args


def test_parse_keeps_bbox_placeholders_verbatim():
    raw = '# THE HAWFINCH\n\n<img src="images/bbox_102_300_880_640.jpg" />\n\nnest itself\n'
    body = {"choices": [{"message": {"role": "assistant", "content": raw}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 8200, "completion_tokens": 40}}
    t = chat_model("ovisocr3").parse(body, backend="served x")
    assert t.text == raw and t.extra["raw"] == raw                     # bbox blocks kept
    m = t.steps[0]
    assert (m.name, m.revision) == ("ATH-MaaS/OvisOCR3", REVISIONS["ATH-MaaS/OvisOCR3"])
    assert m.measurements == {"prompt_tokens": 8200, "completion_tokens": 40, "finish_reason": "stop"}
    assert m.settings["chat_template_kwargs"] == {"enable_thinking": False}
