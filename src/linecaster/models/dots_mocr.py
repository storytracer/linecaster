"""rednote-hilab/dots.mocr: request, parse and serve flags exactly as the BHL OCR board ran it.

Source: the board's saturate driver ``dots-mocr-port.py`` (in the board's evaluation harness), a port of
Daniel van Strien's ``uv-scripts/ocr/dots-mocr.py``; where the two differ, this follows the driver:

* plain OCR mode only: prompt ``Extract the text content from this image.``; the output is plain text,
  not layout JSON (the layout modes are not used), so there is nothing to convert;
* message = the image, then a text part that starts with vLLM's dots placeholder
  ``<|img|><|imgpad|><|endofimg|>`` followed by the prompt (upstream's ``dots_mocr/model/inference.py``
  server client); with ``--chat-template-content-format string`` vLLM then adds no placeholder of its own;
* the image at full resolution, no resize: RGB PNG/JPEG bytes as they are, anything else converted to
  RGB and sent as PNG (the model's processor clamps to its own ``max_pixels`` 11289600);
* sampling from upstream ``inference.py``: temperature 0.1, top_p 0.9; max_tokens 16384 (the driver's:
  a full-size page is at most 14400 image tokens, 14400 + 16384 < 32768);
* serve flags: ``--max-model-len 32768``, ``--trust-remote-code``, ``--chat-template-content-format
  string`` (both from the card's ``vllm serve`` line), ``--no-enable-prefix-caching
  --mm-processor-cache-gb 0 --limit-mm-per-prompt '{"image": 1}'``;
* model revision pinned to the board's checkpoint.

The completion is stored verbatim; the board's post-processing (strip, and an empty completion is an
error) stays in the harness (``normalize_outputs``, keyed on the model id). The board's vLLM is 0.26.0
(``vllm/vllm-openai:v0.26.0``; the recipe's 0.29.0 is newer than the board's). ``--gpu-memory-utilization``
is the deployment's choice (board: 0.6 on an L40S, 4 pages in flight) and not part of the spec.
"""
from __future__ import annotations

import base64
import io
from typing import Any, ClassVar

from . import ChatModel

PROMPT = "Extract the text content from this image."
IMAGE_PLACEHOLDER = "<|img|><|imgpad|><|endofimg|>"
#: formats sent byte-for-byte when the image is already RGB (the driver's ``PASSTHROUGH_FORMATS``)
PASSTHROUGH_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg"}
MAX_MODEL_LEN, MAX_TOKENS = 32768, 16384


def encode_image(data: bytes) -> tuple[str, str]:
    """``(mime, base64)`` of a page image at full resolution, as the driver's ``encode_image``."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        mime = PASSTHROUGH_FORMATS.get(img.format)
        if mime and img.mode == "RGB":
            return mime, base64.b64encode(data).decode()
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
    return "image/png", base64.b64encode(buf.getvalue()).decode()


class DotsMOCR(ChatModel):
    model: ClassVar[str] = "rednote-hilab/dots.mocr"
    revision: ClassVar[str | None] = "e539fbb52280393adc081b289ec597430a0f9031"
    page_longest: ClassVar[int | None] = None       # full resolution
    sampling: ClassVar[dict[str, Any]] = {"max_tokens": MAX_TOKENS, "temperature": 0.1, "top_p": 0.9}
    serve_args: ClassVar[list[str]] = [
        "--max-model-len", str(MAX_MODEL_LEN),
        "--trust-remote-code",
        "--chat-template-content-format", "string",
        "--no-enable-prefix-caching",
        "--mm-processor-cache-gb", "0",
        "--limit-mm-per-prompt", '{"image": 1}',
    ]
    vllm_version: ClassVar[str | None] = "0.26.0"

    def request(self, image: bytes) -> dict:
        mime, b64 = encode_image(image)
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": f"{IMAGE_PLACEHOLDER}{PROMPT}"},
            ]}],
            **self.sampling,
        }

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "prompt": PROMPT,
                "image": {"resize": None, "passthrough": "RGB PNG/JPEG", "else": "RGB PNG"}}
