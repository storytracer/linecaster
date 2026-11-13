"""DeepSeek-OCR and -OCR-2 specs: request body, n-gram guard, serve flags, grounding strip, after the model card."""
from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from linecaster.adapters import chat_model
from linecaster.adapters.deepseek_ocr import strip_grounding
from linecaster.blocks.servers.serve import ChatModelServer

LOGITS_PROCESSOR = "vllm.model_executor.models.deepseek_ocr:NGramPerReqLogitsProcessor"   # the card's

REVISIONS = {"deepseek-ai/DeepSeek-OCR": "9f30c71f441d010e5429c532364a86705536c53a",
             "deepseek-ai/DeepSeek-OCR-2": "aaa02f3811945a91062062994c5c4a3f4c0af2b0"}


def image(w: int, h: int, fmt: str, mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), 200 if mode == "L" else (200, 190, 180)).save(buf, format=fmt)
    return buf.getvalue()


def sent(body: dict) -> tuple[str, bytes]:
    head, b64 = body["messages"][0]["content"][0]["image_url"]["url"].split(",", 1)
    return head, base64.b64decode(b64)


@pytest.mark.parametrize("model", sorted(REVISIONS))
def test_request_matches_the_reference(model):
    data = image(2400, 3600, "JPEG")
    b = chat_model(model).request(data)
    assert b["model"] == model
    image_part, text_part = b["messages"][0]["content"]
    assert image_part["type"] == "image_url"
    assert text_part == {"type": "text", "text": "<|grounding|>Convert the document to markdown."}
    assert sent(b) == ("data:image/jpeg;base64", data)                  # RGB JPEG: byte-for-byte, full size
    assert (b["temperature"], b["max_tokens"], b["skip_special_tokens"]) == (0.0, 4096, False)
    assert b["vllm_xargs"] == {"ngram_size": 30, "window_size": 90, "whitelist_token_ids": [128821, 128822]}
    assert set(b) == {"model", "messages", "temperature", "max_tokens", "skip_special_tokens", "vllm_xargs"}
    assert "mm_processor_kwargs" not in b                               # vLLM's default resolution (Gundam)


@pytest.mark.parametrize("fmt, mode", [("WEBP", "RGB"), ("PNG", "L"), ("JPEG", "L")])
def test_other_images_become_full_size_rgb_png(fmt, mode):
    head, raw = sent(chat_model("deepseek-ocr").request(image(3000, 4500, fmt, mode)))
    assert head == "data:image/png;base64"
    with Image.open(io.BytesIO(raw)) as im:
        assert (im.format, im.mode, im.size) == ("PNG", "RGB", (3000, 4500))


@pytest.mark.parametrize("model", sorted(REVISIONS))
def test_serve_args_match_the_card(model):
    spec = chat_model(model)
    args = spec.vllm_args(0.8, ["--max-num-seqs", "8"])
    assert args[:2] == ["--revision", REVISIONS[model]]
    for flag, value in (("--max-model-len", "8192"), ("--limit-mm-per-prompt", '{"image": 1}'),
                        ("--mm-processor-cache-gb", "0"), ("--gpu-memory-utilization", "0.8")):
        assert args[args.index(flag) + 1] == value
    assert "--trust-remote-code" in args and "--no-enable-prefix-caching" in args
    assert args[-2:] == ["--logits_processors", LOGITS_PROCESSOR]       # last, after the deployment's extras
    cmd = ChatModelServer(spec, port=8000, gpu_memory_utilization=0.8).command()
    assert cmd[:3] == ["vllm", "serve", model] and cmd[-1] == LOGITS_PROCESSOR


def test_v2_is_v1_but_the_checkpoint():
    assert chat_model("deepseek-ocr-2").adapter == chat_model("deepseek-ocr").adapter == "deepseek-ocr"
    assert chat_model("deepseek-ocr-2").settings() == chat_model("deepseek-ocr").settings()


RAW = ("<|ref|>title<|/ref|><|det|>[[120, 80, 880, 130]]<|/det|>\n# THE BIRDS\n\n\n\n"
       "<|ref|>text<|/ref|><|det|>[[100, 150, 900, 600]]<|/det|>\nof Ceylon.\n")


def test_parse_keeps_grounding_verbatim_and_strip_removes_it():
    t = chat_model("deepseek-ocr").parse({"choices": [{"message": {"content": RAW}, "finish_reason": "stop"}], "usage": {}})
    assert t.outputs[0].content == RAW and t.text == RAW
    assert strip_grounding(RAW) == "# THE BIRDS\n\nof Ceylon."
    with pytest.raises(ValueError, match="grounding markup"):
        strip_grounding("text <|det|>[[1, 2, 3, 4]]")
