"""olmOCR-2 spec: request body, serve flags and front-matter parse, as the BHL board driver ran it."""
from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from linecaster.blocks.serve import ServeChatModel
from linecaster.models import chat_model
from linecaster.models.olmocr2 import PROMPT, OlmOCR2, body, split_front_matter

MODEL = "allenai/olmOCR-2-7B-1025-FP8"


def image(w: int, h: int, fmt: str = "WEBP") -> bytes:
    buf = io.BytesIO()
    Image.new("L", (w, h), 200).save(buf, format=fmt)
    return buf.getvalue()


def sent_image(b: dict) -> Image.Image:
    url = b["messages"][0]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))


def completion(content, finish="stop", usage=None):
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 40} if usage is None else usage}


@pytest.mark.parametrize("size,expected", [
    ((2000, 3000), (859, 1288)),     # downscaled
    ((600, 400), (1288, 859)),       # upscaled (landscape)
    ((1000, 1288), (1000, 1288)),    # already at the target: untouched
])
def test_request_forces_longest_side_to_1288(size, expected):
    im = sent_image(OlmOCR2().request(image(*size)))
    assert im.format == "PNG" and im.mode == "RGB" and im.size == expected


def test_request_is_text_then_image_with_board_sampling():
    b = chat_model(MODEL).request(image(800, 1200, "JPEG"))
    assert b["model"] == MODEL
    assert len(b["messages"]) == 1 and b["messages"][0]["role"] == "user"
    content = b["messages"][0]["content"]
    assert [c["type"] for c in content] == ["text", "image_url"]
    assert content[0]["text"] == PROMPT
    assert PROMPT.startswith("Attached is one page of a document") and PROMPT.endswith("is_diagram parameters.")
    assert (b["temperature"], b["repetition_penalty"], b["max_tokens"]) == (0.1, 1.05, 8192)
    assert b["stop"] == ["<|im_end|>", "<|endoftext|>"]
    assert set(b) == {"model", "messages", "temperature", "repetition_penalty", "stop", "max_tokens"}


def test_serve_args_match_the_board_driver():
    spec = OlmOCR2()
    args = spec.vllm_args(0.8)
    assert args[:2] == ["--revision", "40bd7202494b8264ee17ada08b401b5aab7a9ce1"]
    for flag in (["--max-model-len", "16384"], ["--limit-mm-per-prompt", '{"image": 1}'],
                 ["--mm-processor-cache-gb", "0"], ["--gpu-memory-utilization", "0.8"]):
        i = args.index(flag[0])
        assert args[i:i + 2] == flag
    assert "--no-enable-prefix-caching" in args and "--trust-remote-code" not in args
    assert spec.sampling["max_tokens"] < 16384
    cmd = ServeChatModel(spec, port=8123, gpu_memory_utilization=0.8).command()
    assert cmd[:3] == ["vllm", "serve", MODEL]


RAW = ("---\nprimary_language: en\nis_rotation_valid: True\nrotation_correction: 0\nis_table: false\n"
       "is_diagram: false\n---\nFIG. 1.—Head of\n\nthe beetle.\n")


def test_parse_keeps_raw_verbatim_and_reads_front_matter():
    t = OlmOCR2().parse(completion(RAW), backend="served x")
    assert t.extra["raw"] == RAW and t.text == RAW and t.extra["finish_reason"] == "stop"
    assert t.extra["front_matter"] == {"primary_language": "en", "is_rotation_valid": True,
                                       "rotation_correction": 0, "is_table": False, "is_diagram": False}
    m = t.model[0]
    assert (m.step, m.name, m.revision, m.backend) == ("page", MODEL, "40bd7202494b8264ee17ada08b401b5aab7a9ce1",
                                                       "served x")
    assert m.measurements["completion_tokens"] == 40


def test_body_splits_like_the_board_harness():
    assert body(RAW) == "FIG. 1.—Head of\n\nthe beetle."
    # a blank page: front matter alone, no line after the closing fence -> empty body
    meta, text = split_front_matter("---\nprimary_language: null\nis_table: False\n---")
    assert meta == {"primary_language": None, "is_table": False} and text == ""
    # no front matter: the stripped text unchanged
    assert split_front_matter("\n plain text \n") == (None, "plain text")
    t = OlmOCR2().parse(completion(None, usage={}))
    assert t.extra["raw"] == "" and t.extra["front_matter"] is None
