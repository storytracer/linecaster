"""Adapter ``glm-ocr``: zai-org/GLM-OCR (preset ``glm-ocr``).

* message = the page image, then ``settings.prompt`` (image before text);
* the image RGB-converted and, only if its area exceeds ``settings.image.max_pixels`` (the processor's
  ceiling), downscaled by sqrt(max_pixels / area) with the sides truncated to ints, LANCZOS; never upscaled;
  PNG (``encode_png``).
"""
from __future__ import annotations

import io
from typing import Any, ClassVar

from . import ChatAdapter, data_url, png_bytes


def encode_png(image: bytes, max_pixels: int) -> str:
    """RGB, downscaled to ``max_pixels`` if larger (never up), base64 PNG."""
    from PIL import Image

    with Image.open(io.BytesIO(image)) as im:
        img = im.convert("RGB")
    w, h = img.size
    if w * h > max_pixels:
        scale = (max_pixels / (w * h)) ** 0.5
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    return png_bytes(img)


class GLMOCRAdapter(ChatAdapter):
    adapter: ClassVar[str] = "glm-ocr"

    @property
    def max_pixels(self) -> int:
        return int(self.config["image"]["max_pixels"])

    def request(self, image: bytes) -> dict:
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                data_url("image/png", encode_png(image, self.max_pixels)),
                {"type": "text", "text": self.prompt},
            ]}],
            **self.sampling,
        }

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "prompt": self.prompt,
                "image": {"format": "png", "max_pixels": self.max_pixels, "resize": "down only, LANCZOS"}}
