"""Adapter ``paddleocr-vl``: PaddleOCR-VL's VLM alone on the whole page (preset ``paddleocr-vl-1.6``), not
PaddleOCR-VL's PP-DocLayout + VLM pipeline.

* message = the page image, then ``settings.prompt`` (``OCR:``, the task mode ``ocr``);
* the image RGB-converted and resized client-side by the recipe's ``smart_resize``: both sides rounded to
  multiples of ``settings.image.factor``, the area brought into [min_pixels, max_pixels] (floor when
  shrinking, ceil when growing; aspect kept), LANCZOS, PNG; an image already on that grid is sent unresized
  (still re-encoded as PNG).
"""
from __future__ import annotations

import io
import math
from typing import Any, ClassVar

from . import ChatAdapter, data_url, png_bytes


def smart_resize(h: int, w: int, factor: int, min_pixels: int, max_pixels: int) -> tuple[int, int]:
    """``(height, width)`` a page is resized to (the uv-scripts recipe's ``smart_resize``, verbatim)."""
    h_bar = round(h / factor) * factor
    w_bar = round(w / factor) * factor
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt(h * w / max_pixels)
        h_bar = math.floor(h / beta / factor) * factor
        w_bar = math.floor(w / beta / factor) * factor
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (h * w))
        h_bar = math.ceil(h * beta / factor) * factor
        w_bar = math.ceil(w * beta / factor) * factor
    return h_bar, w_bar


class PaddleOCRVLAdapter(ChatAdapter):
    adapter: ClassVar[str] = "paddleocr-vl"

    def smart_resize(self, h: int, w: int) -> tuple[int, int]:
        i = self.config["image"]
        return smart_resize(h, w, int(i["factor"]), int(i["min_pixels"]), int(i["max_pixels"]))

    def encode_png(self, image: bytes) -> str:
        """RGB, ``smart_resize`` (LANCZOS) if the size changes, base64 PNG."""
        from PIL import Image

        with Image.open(io.BytesIO(image)) as im:
            img = im.convert("RGB")
        w, h = img.size
        h_bar, w_bar = self.smart_resize(h, w)
        if (w_bar, h_bar) != (w, h):
            img = img.resize((w_bar, h_bar), Image.LANCZOS)
        return png_bytes(img)

    def request(self, image: bytes) -> dict:
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                data_url("image/png", self.encode_png(image)),
                {"type": "text", "text": self.prompt},
            ]}],
            **self.sampling,
        }

    def settings(self) -> dict[str, Any]:
        i = self.config["image"]
        return {**super().settings(), "prompt": self.prompt,
                "image": {"format": "png", "resize": f"smart_resize ({i['factor']}-px grid, {i['min_pixels']}-"
                                                     f"{i['max_pixels']} px), LANCZOS"}}
