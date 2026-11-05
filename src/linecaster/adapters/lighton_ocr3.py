"""Adapter ``lighton-ocr-3``: LightOnOCR-3's transcription call (presets ``lightonocr-3-4b`` and
``lightonocr-3-0.8b``, which differ only in the checkpoint).

* message = the page image ONLY, no text part (the card's transcription call; grounding is another output);
* the image RGB-converted and ``thumbnail((n, n))``-ed with ``n = settings.image.longest_side_px`` (2048),
  then PNG. ``thumbnail`` only ever downscales and keeps the aspect ratio, so a smaller page is sent as it
  is (unlike LightOnOCR-2's forced size);
* ``chat_template_kwargs`` from the preset with every request (thinking off).
"""
from __future__ import annotations

import base64
import io
from typing import Any, ClassVar

from . import ChatModel, data_url, png_bytes


def png_thumbnail(image: bytes, longest: int) -> tuple[str, tuple[int, int]]:
    """RGB, ``thumbnail((longest, longest))`` (downscale only, Pillow's default filter), base64 PNG; and the size."""
    from PIL import Image

    with Image.open(io.BytesIO(image)) as im:
        img = im.convert("RGB")
    img.thumbnail((longest, longest))
    return png_bytes(img), img.size


class LightOnOCR3(ChatModel):
    adapter: ClassVar[str] = "lighton-ocr-3"

    @property
    def target_longest(self) -> int:
        return int(self.config["image"]["longest_side_px"])

    @property
    def chat_template_kwargs(self) -> dict[str, Any]:
        return dict(self.config.get("chat_template_kwargs") or {})

    def request(self, image: bytes) -> dict:
        b64, _ = png_thumbnail(image, self.target_longest)
        return self._body(b64)

    def request_region(self, crop: bytes, region=None) -> dict:
        """A region crop, already at the page's scale: PNG as it is, no further resize."""
        return self._body(base64.b64encode(crop).decode())

    def _body(self, b64: str) -> dict:
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [data_url("image/png", b64)]}],
            **self.sampling,
            "chat_template_kwargs": self.chat_template_kwargs,
        }

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "image": {"format": "png", "longest_side_px": self.target_longest,
                                                "resize": "thumbnail (down only), Pillow default filter"},
                "chat_template_kwargs": self.chat_template_kwargs, "prompt": None}
