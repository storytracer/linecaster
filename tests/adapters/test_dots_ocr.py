"""The dots.ocr spec: request, parse and serve flags after the model card."""
from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from linecaster.adapters import chat_model
from linecaster.blocks.servers.serve import ChatModelServer

REVISION = "c0111ce6bc07803dbc267932ffef0ae3a51dc951"


def image(w: int, h: int, fmt: str, mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), 200 if mode == "L" else (200, 190, 180)).save(buf, format=fmt)
    return buf.getvalue()


def sent(body: dict) -> tuple[str, bytes]:
    head, b64 = body["messages"][0]["content"][0]["image_url"]["url"].split(",", 1)
    return head, base64.b64decode(b64)


def test_registry_and_revision():
    spec = chat_model("rednote-hilab/dots.ocr")
    assert spec.adapter == "dots" and spec.preset == "dots-ocr@1" and spec.revision == REVISION


def test_request_matches_the_reference():
    data = image(2400, 3600, "JPEG")
    body = chat_model("dots-ocr").request(data)
    assert set(body) == {"model", "messages", "temperature", "max_tokens"}   # no top_p
    assert body["model"] == "rednote-hilab/dots.ocr"
    assert (body["temperature"], body["max_tokens"]) == (0.0, 8192)
    image_part, text_part = body["messages"][0]["content"]
    assert image_part["type"] == "image_url"
    assert text_part == {"type": "text", "text": "Extract the text content from this image."}   # no placeholder
    head, raw = sent(body)
    assert head == "data:image/jpeg;base64" and raw == data          # RGB JPEG: byte-for-byte, full size


@pytest.mark.parametrize("fmt, mode", [("WEBP", "RGB"), ("PNG", "L"), ("JPEG", "L"), ("PNG", "RGBA")])
def test_other_images_become_full_size_rgb_png(fmt, mode):
    head, raw = sent(chat_model("dots-ocr").request(image(3000, 4500, fmt, mode)))
    assert head == "data:image/png;base64"
    with Image.open(io.BytesIO(raw)) as im:
        assert (im.format, im.mode, im.size) == ("PNG", "RGB", (3000, 4500))


def test_serve_args_match_the_card():
    cmd = ChatModelServer(chat_model("dots-ocr"), port=8000, gpu_memory_utilization=0.6).command()
    assert cmd[:3] == ["vllm", "serve", "rednote-hilab/dots.ocr"]
    args = cmd[7:]
    for flag in (["--revision", REVISION], ["--max-model-len", "32768"], ["--mm-processor-cache-gb", "0"],
                 ["--limit-mm-per-prompt", '{"image": 1}'], ["--gpu-memory-utilization", "0.6"]):
        i = args.index(flag[0])
        assert args[i:i + 2] == flag
    assert {"--trust-remote-code", "--no-enable-prefix-caching"} <= set(args)
    assert "--chat-template-content-format" not in args and "--served-model-name" not in args


def test_parse_keeps_the_completion_verbatim():
    raw = "\nPROCEEDINGS OF THE ZOOLOGICAL SOCIETY\n\n12. Helix (Patula) rotundata, Müll.\n"
    body = {"choices": [{"message": {"role": "assistant", "content": raw}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 9000, "completion_tokens": 30}}
    t = chat_model("dots-ocr").parse(body, backend="served vllm")
    assert t.text == raw and t.outputs[0].content == raw                    # no strip
    m = t.annotators[0]
    assert (m.step, m.name, m.revision) == ("recognition", "rednote-hilab/dots.ocr", REVISION)
    assert m.measurements == {"prompt_tokens": 9000, "completion_tokens": 30, "finish_reason": "stop"}
    assert m.settings["prompt"] == "Extract the text content from this image."
