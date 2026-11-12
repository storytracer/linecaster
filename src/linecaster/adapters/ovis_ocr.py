"""Adapter ``ovis-ocr``: OvisOCR2 and OvisOCR3 (presets ``ovisocr2``, ``ovisocr3``: the same request with the
checkpoint and the prompt of each card).

* message = the page image, then ``settings.prompt`` as a text part (OvisOCR2's starts with a newline,
  the server recipe's; OvisOCR3's is the repo's ``prompts/document_markdown.txt``, the same text without it);
* the image RGB-converted, downscaled with LANCZOS to at most ``settings.image.max_pixels`` (sides
  ``int(w * s)``, ``int(h * s)`` with ``s = sqrt(max / (w * h))``), never upscaled, then JPEG at
  ``settings.image.jpeg_quality`` (every image, also when it fits): ``encode_jpeg``, shared with Qwen3.5;
* ``settings.chat_template_kwargs`` with every request (thinking off).

The completion is stored verbatim, ``<img src="images/bbox_...">`` placeholders and all; dropping
those blocks is left to the consumer.
"""
from __future__ import annotations

import base64
import io
import math
from typing import Any, ClassVar

from . import ChatAdapter, data_url


def encode_jpeg(image: bytes, max_pixels: int, quality: int) -> tuple[str, tuple[int, int]]:
    """RGB, downscaled to ``max_pixels`` area if larger (LANCZOS), JPEG at
    ``quality``; base64 and the size."""
    from PIL import Image

    from ..images.pixels import rgb_image

    img = rgb_image(image)
    w, h = img.size
    if w * h > max_pixels:
        scale = math.sqrt(max_pixels / (w * h))
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode(), img.size


class OvisOCRAdapter(ChatAdapter):
    adapter: ClassVar[str] = "ovis-ocr"

    @property
    def max_pixels(self) -> int:
        return int(self.config["image"]["max_pixels"])

    @property
    def jpeg_quality(self) -> int:
        return int(self.config["image"]["jpeg_quality"])

    @property
    def chat_template_kwargs(self) -> dict[str, Any]:
        return dict(self.config.get("chat_template_kwargs") or {})

    def request(self, image: bytes) -> dict:
        b64, _ = encode_jpeg(image, self.max_pixels, self.jpeg_quality)
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [data_url("image/jpeg", b64), {"type": "text", "text": self.prompt}]}],
            **self.sampling,
            "chat_template_kwargs": self.chat_template_kwargs,
        }

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "prompt": self.prompt, "chat_template_kwargs": self.chat_template_kwargs,
                "image": {"format": "jpeg", "quality": self.jpeg_quality, "max_pixels": self.max_pixels,
                          "resize": "down only, LANCZOS"}}
