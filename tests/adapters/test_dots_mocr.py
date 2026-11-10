"""The dots.mocr spec: request, parse and serve flags after the model card."""
from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from linecaster.adapters import chat_model
from linecaster.blocks.servers.serve import ChatModelServer


def image(w: int, h: int, fmt: str, mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), 200 if mode == "L" else (200, 190, 180)).save(buf, format=fmt)
    return buf.getvalue()


def completion(content, finish="stop", usage=None):
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 7012, "completion_tokens": 431} if usage is None else usage}


def sent(body: dict) -> tuple[str, bytes]:
    url = body["messages"][0]["content"][0]["image_url"]["url"]
    head, b64 = url.split(",", 1)
    return head, base64.b64decode(b64)


def test_request_matches_the_reference():
    data = image(2400, 3600, "JPEG")
    body = chat_model("rednote-hilab/dots.mocr").request(data)
    assert body["model"] == "rednote-hilab/dots.mocr"
    assert (body["max_tokens"], body["temperature"], body["top_p"]) == (16384, 0.1, 0.9)
    image_part, text_part = body["messages"][0]["content"]
    assert image_part["type"] == "image_url"
    assert text_part == {"type": "text", "text": "<|img|><|imgpad|><|endofimg|>Extract the text content from this image."}
    head, raw = sent(body)
    assert head == "data:image/jpeg;base64" and raw == data          # RGB JPEG: byte-for-byte, full size


@pytest.mark.parametrize("fmt, mode", [("WEBP", "RGB"), ("PNG", "L"), ("JPEG", "L"), ("PNG", "RGBA")])
def test_other_images_become_full_size_rgb_png(fmt, mode):
    head, raw = sent(chat_model("dots-mocr").request(image(3000, 4500, fmt, mode)))
    assert head == "data:image/png;base64"
    with Image.open(io.BytesIO(raw)) as im:
        assert (im.format, im.mode, im.size) == ("PNG", "RGB", (3000, 4500))     # no resize


def test_serve_args_match_the_card():
    cmd = ChatModelServer(chat_model("dots-mocr"), port=8000, gpu_memory_utilization=0.6).command()
    assert cmd[:3] == ["vllm", "serve", "rednote-hilab/dots.mocr"]
    args = cmd[7:]
    pairs = {args[i]: args[i + 1] for i in range(len(args) - 1) if args[i].startswith("--") and not args[i + 1].startswith("--")}
    assert pairs["--revision"] == "e539fbb52280393adc081b289ec597430a0f9031"
    assert pairs["--max-model-len"] == "32768"
    assert pairs["--chat-template-content-format"] == "string"
    assert pairs["--mm-processor-cache-gb"] == "0"
    assert pairs["--limit-mm-per-prompt"] == '{"image": 1}'
    assert pairs["--gpu-memory-utilization"] == "0.6"
    assert {"--trust-remote-code", "--no-enable-prefix-caching"} <= set(args)
    assert "--served-model-name" not in args


def test_parse_keeps_the_completion_verbatim():
    raw = ("\nPROCEEDINGS OF THE ZOOLOGICAL SOCIETY\n\n"
           "12. Helix (Patula) rotundata, Müll.\n"
           "Hab. Near Bristol, under stones; rare.\n\n"
           "Shell 6 mm. × 2·5 mm.; whorls 5½.\n")
    t = chat_model("dots-mocr").parse(completion(raw), backend="served vllm")
    assert t.text == raw and t.extra["raw"] == raw                    # no strip, no empty check
    assert [ln.text for ln in t.lines][1] == "PROCEEDINGS OF THE ZOOLOGICAL SOCIETY"
    m = t.steps[0]
    assert (m.step, m.name, m.revision) == ("recognition", "rednote-hilab/dots.mocr", "e539fbb52280393adc081b289ec597430a0f9031")
    assert m.measurements == {"prompt_tokens": 7012, "completion_tokens": 431, "finish_reason": "stop"}
    assert m.settings["prompt"] == "Extract the text content from this image."
    assert chat_model("dots-mocr").parse(completion(None, usage={})).text == ""
