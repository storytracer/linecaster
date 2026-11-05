"""Adapter ``lighton-ocr-2``: LightOnOCR-2's trained request format, the page image only (presets
``lightonocr-2-1b`` for pages and ``lightonocr-2-1b-regions`` for layout regions).

* message = the page image ONLY, no text part (LightOnOCR-2's trained format, per the card);
* the image re-encoded as PNG with the longest side forced to exactly ``settings.image.longest_side_px``
  (1540: the card's "target longest dimension", ``processor_config`` longest_edge), in both directions;
* a region crop (``RegionRecognizer``) is already cut at that page scale (``page_longest``) and sent as it is.

Sampling, flags and the reasons for them are in the presets.
"""
from __future__ import annotations

import base64
from typing import Any, ClassVar

from . import ChatAdapter, data_url, png_longest


class LightOnOCR2Adapter(ChatAdapter):
    adapter: ClassVar[str] = "lighton-ocr-2"

    @property
    def target_longest(self) -> int:
        return int(self.config["image"]["longest_side_px"])

    def request(self, image: bytes) -> dict:
        b64, _ = png_longest(image, self.target_longest)
        return self._body(b64)

    def request_region(self, crop: bytes, region=None) -> dict:
        """A region crop, already at the page's scale: PNG as it is, no further resize."""
        return self._body(base64.b64encode(crop).decode())

    def _body(self, b64: str) -> dict:
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [data_url("image/png", b64)]}],
            **self.sampling,
        }

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "image": {"format": "png", "longest_side_px": self.target_longest,
                                                "resize": "forced (up and down), LANCZOS"},
                "prompt": None}
