"""zai-org/GLM-OCR: request, parse and serve flags exactly as the BHL OCR board ran it.

Source: the board's saturate driver ``glm-ocr-port.py`` (in the board's evaluation harness), a port of
Daniel van Strien's ``uv-scripts/ocr/glm-ocr.py``:

* message = the page image, then the card's prompt ``Text Recognition:`` (image before text);
* the image RGB-converted and, only if its area exceeds the processor's ceiling (``max_pixels``
  9633792, ``preprocessor_config.json``), downscaled by sqrt(max_pixels / area) with the sides
  truncated to ints, LANCZOS; never upscaled; PNG;
* temperature 0.01, top_p 1e-05, repetition_penalty 1.1 (the authors' SDK values, via the recipe),
  max_tokens 8192 (card);
* serve flags: ``--max-model-len 32768 --no-enable-prefix-caching --mm-processor-cache-gb 0
  --limit-mm-per-prompt '{"image": 1}'``; no ``--trust-remote-code`` (the architecture is in vLLM);
* model revision pinned to the board's checkpoint; vLLM 0.26.0 (``vllm/vllm-openai:v0.26.0``, the
  board-wide pin instead of the card's nightly).

The completion is stored verbatim; the board's post-processing (strip, and an empty completion is an
error) stays in the harness. ``--gpu-memory-utilization`` is the deployment's choice (board 0.8 on an
A10G) and not part of the spec.
"""
from __future__ import annotations

import base64
import io
from typing import Any, ClassVar

from . import ChatModel

MAX_PIXELS = 9633792


def encode_png(image: bytes, max_pixels: int = MAX_PIXELS) -> str:
    """The driver's ``encode_png``: RGB, downscaled to ``max_pixels`` if larger (never up), base64 PNG."""
    from PIL import Image

    with Image.open(io.BytesIO(image)) as im:
        img = im.convert("RGB")
    w, h = img.size
    if w * h > max_pixels:
        scale = (max_pixels / (w * h)) ** 0.5
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class GLMOCR(ChatModel):
    model: ClassVar[str] = "zai-org/GLM-OCR"
    revision: ClassVar[str | None] = "ca5d8b3e287e52589e37c28385d9655ee4372f9d"
    prompt: ClassVar[str] = "Text Recognition:"
    max_pixels: ClassVar[int] = MAX_PIXELS
    sampling: ClassVar[dict[str, Any]] = {"temperature": 0.01, "top_p": 0.00001, "repetition_penalty": 1.1,
                                          "max_tokens": 8192}
    serve_args: ClassVar[list[str]] = [
        "--max-model-len", "32768",
        "--no-enable-prefix-caching",
        "--mm-processor-cache-gb", "0",
        "--limit-mm-per-prompt", '{"image": 1}',
    ]
    vllm_version: ClassVar[str | None] = "0.26.0"

    def request(self, image: bytes) -> dict:
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{encode_png(image, self.max_pixels)}"}},
                {"type": "text", "text": self.prompt},
            ]}],
            **self.sampling,
        }

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "prompt": self.prompt,
                "image": {"format": "png", "max_pixels": self.max_pixels, "resize": "down only, LANCZOS"}}
