"""The chandra-ocr-2 spec: request, parse and serve flags after the model card."""
from __future__ import annotations

import base64
import hashlib
import io
import random

import pytest
from PIL import Image

from linecaster.adapters import chat_model
from linecaster.adapters.chandra_ocr2 import scale_to_fit
from linecaster.blocks.servers.serve import ChatModelServer

OCR_LAYOUT_PROMPT = chat_model("chandra-ocr-2").prompt   # the preset's, verbatim

REVISION = "af93b47dba1b47b6640c86ccf487ed2260ab9a09"


FAST_ENCODING = {"WEBP": {"method": 0}, "PNG": {"compress_level": 1}}


def image(w: int, h: int, fmt: str = "WEBP", mode: str = "L") -> bytes:
    """A page of seeded noise; WebP and PNG are encoded at their fastest settings, which the request reads the same."""
    noise = Image.frombytes("L", (w, h), random.Random(0).randbytes(w * h))
    buf = io.BytesIO()
    noise.convert(mode).save(buf, format=fmt, **FAST_ENCODING.get(fmt, {}))
    return buf.getvalue()


def sent(body: dict) -> Image.Image:
    url = body["messages"][0]["content"][0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))


def test_registry_and_revision():
    spec = chat_model("datalab-to/chandra-ocr-2")
    assert spec.adapter == "chandra-ocr" and spec.revision == REVISION


def test_prompt_is_chandra_v020_ocr_layout():
    assert hashlib.sha256(OCR_LAYOUT_PROMPT.encode()).hexdigest()[:16] == "025935f3e1de1acd"
    assert OCR_LAYOUT_PROMPT.startswith("OCR this image to HTML, arranged as layout blocks.")


def test_request_body_is_the_reference():
    body = chat_model("chandra-ocr-2").request(image(2400, 3600, "JPEG", "RGB"))
    assert set(body) == {"model", "messages", "temperature", "top_p", "max_tokens"}
    assert body["model"] == "datalab-to/chandra-ocr-2"
    assert (body["temperature"], body["top_p"], body["max_tokens"]) == (0.0, 0.1, 12384)
    image_part, text_part = body["messages"][0]["content"]             # image first, then the prompt
    assert image_part["type"] == "image_url"
    assert text_part == {"type": "text", "text": OCR_LAYOUT_PROMPT}


@pytest.mark.parametrize("size", [(2400, 3600), (3600, 2400), pytest.param((5000, 7000), marks=pytest.mark.slow)])
def test_large_pages_scale_to_the_grid_under_the_pixel_cap(size):
    im = sent(chat_model("chandra-ocr-2").request(image(*size)))
    w, h = im.size
    assert (im.format, im.mode) == ("PNG", "RGB")
    assert w % 28 == 0 and h % 28 == 0 and w * h <= 3072 * 2048
    assert abs(w / h - size[0] / size[1]) < 0.02


def test_scale_to_fit_matches_the_vendor():
    # 2400x3600: scale sqrt(6291456 / 8640000) -> 73 x 110 blocks = 2044x3080, over the cap by 4064 px;
    # the refinement loop takes a block off the height (less aspect loss) -> 2044x3052
    assert scale_to_fit(Image.new("RGB", (2400, 3600))).size == (2044, 3052)
    small = Image.new("RGB", (1680, 2520))
    assert scale_to_fit(small) is small                                # on the grid, in bounds: untouched
    assert scale_to_fit(Image.new("RGB", (100, 100))).size == (224, 224)   # below min pixels: upscaled


def test_serve_args_match_the_card():
    cmd = ChatModelServer(chat_model("chandra-ocr-2"), port=8000, gpu_memory_utilization=0.8).command()
    assert cmd[:3] == ["vllm", "serve", "datalab-to/chandra-ocr-2"]
    args = cmd[7:]
    for flag in (["--revision", REVISION], ["--max-model-len", "20480"],
                 ["--mm-processor-kwargs", '{"min_pixels": 3136, "max_pixels": 6291456}'],
                 ["--limit-mm-per-prompt", '{"image": 1, "video": 0}'], ["--mm-processor-cache-gb", "0"],
                 ["--dtype", "bfloat16"], ["--gpu-memory-utilization", "0.8"]):
        i = args.index(flag[0])
        assert args[i:i + 2] == flag
    assert "--no-enable-prefix-caching" in args
    assert "--trust-remote-code" not in args and "--served-model-name" not in args


def test_parse_keeps_the_html_verbatim():
    raw = ('<div data-bbox="102 61 898 90" data-label="Page-Header"><p>PROCEEDINGS</p></div>\n'
           '<div data-bbox="100 120 900 400" data-label="Text"><p>Helix rotundata, <i>Müll.</i></p></div>')
    body = {"choices": [{"message": {"role": "assistant", "content": raw}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 6700, "completion_tokens": 80}}
    t = chat_model("chandra-ocr-2").parse(body, backend="served x")
    assert t.text == raw and t.extra["raw"] == raw                     # HTML -> Markdown is left to the consumer
    m = t.steps[0]
    assert (m.step, m.name, m.revision) == ("recognition", "datalab-to/chandra-ocr-2", REVISION)
    assert m.measurements == {"prompt_tokens": 6700, "completion_tokens": 80, "finish_reason": "stop"}
    assert m.settings["attempts"] == 1
