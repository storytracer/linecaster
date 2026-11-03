"""PaddlePaddle/PaddleOCR-VL-1.6: request, parse and serve flags exactly as the BHL OCR board ran it.

Source: the board's saturate driver ``paddleocr-vl-16-port.py`` (in the board's evaluation harness), a
port of Daniel van Strien's ``uv-scripts/ocr/paddleocr-vl-1.6.py``. The board runs the VLM alone on the
whole page (task mode ``ocr``), not PaddleOCR-VL's layout + VLM pipeline (PP-DocLayout regions read one
by one through PaddleX), so this is a page spec for ``ChatPageStep``:

* message = the page image, then the text part ``OCR:``;
* the image RGB-converted and resized client-side by the recipe's ``smart_resize``: both sides rounded
  to multiples of 28, the area brought into [28·28·130, 28·28·1280] px (floor when shrinking, ceil
  when growing; aspect kept), LANCZOS, PNG; an image already on that grid is sent unresized (still
  re-encoded as PNG);
* temperature 0.0, max_tokens 4096;
* serve flags: ``--max-model-len 8192 --trust-remote-code --enforce-eager --max-num-batched-tokens
  16384 --no-enable-prefix-caching --mm-processor-cache-gb 0 --limit-mm-per-prompt '{"image": 1}'``;
* model revision pinned to the board's checkpoint; vLLM 0.26.0 (``vllm/vllm-openai:v0.26.0``).

The completion is stored verbatim; the board's post-processing (a strip) stays in the harness.
``--gpu-memory-utilization`` is the deployment's choice (board 0.8 on an A10G) and not part of the spec.
"""
from __future__ import annotations

import base64
import io
import math
from typing import Any, ClassVar

from . import ChatModel

FACTOR = 28
MIN_PIXELS = 28 * 28 * 130
MAX_PIXELS = 28 * 28 * 1280


def smart_resize(h: int, w: int) -> tuple[int, int]:
    """``(height, width)`` the driver resizes a page to (the recipe's ``smart_resize``, verbatim)."""
    h_bar = round(h / FACTOR) * FACTOR
    w_bar = round(w / FACTOR) * FACTOR
    if h_bar * w_bar > MAX_PIXELS:
        beta = math.sqrt(h * w / MAX_PIXELS)
        h_bar = math.floor(h / beta / FACTOR) * FACTOR
        w_bar = math.floor(w / beta / FACTOR) * FACTOR
    elif h_bar * w_bar < MIN_PIXELS:
        beta = math.sqrt(MIN_PIXELS / (h * w))
        h_bar = math.ceil(h * beta / FACTOR) * FACTOR
        w_bar = math.ceil(w * beta / FACTOR) * FACTOR
    return h_bar, w_bar


def encode_png(image: bytes) -> str:
    """The driver's ``encode_png``: RGB, ``smart_resize`` (LANCZOS) if the size changes, base64 PNG."""
    from PIL import Image

    with Image.open(io.BytesIO(image)) as im:
        img = im.convert("RGB")
    w, h = img.size
    h_bar, w_bar = smart_resize(h, w)
    if (w_bar, h_bar) != (w, h):
        img = img.resize((w_bar, h_bar), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class PaddleOCRVL16(ChatModel):
    model: ClassVar[str] = "PaddlePaddle/PaddleOCR-VL-1.6"
    revision: ClassVar[str | None] = "66317acc4c9fc17bd154591ce650735cd2855f3e"
    prompt: ClassVar[str] = "OCR:"
    sampling: ClassVar[dict[str, Any]] = {"temperature": 0.0, "max_tokens": 4096}
    serve_args: ClassVar[list[str]] = [
        "--max-model-len", "8192",
        "--trust-remote-code",
        "--enforce-eager",
        "--max-num-batched-tokens", "16384",
        "--no-enable-prefix-caching",
        "--mm-processor-cache-gb", "0",
        "--limit-mm-per-prompt", '{"image": 1}',
    ]
    vllm_version: ClassVar[str | None] = "0.26.0"

    def request(self, image: bytes) -> dict:
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encode_png(image)}"}},
                {"type": "text", "text": self.prompt},
            ]}],
            **self.sampling,
        }

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "prompt": self.prompt,
                "image": {"format": "png", "resize": "smart_resize (28-px grid, 101920-1003520 px), LANCZOS"}}
