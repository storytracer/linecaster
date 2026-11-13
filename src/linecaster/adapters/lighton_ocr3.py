"""Adapter ``lighton-ocr-3``: LightOnOCR-3's transcription call (presets ``lightonocr-3-4b`` and
``lightonocr-3-0.8b``, which differ only in the checkpoint).

* message = the page image ONLY, no text part (the card's transcription call; grounding is another output);
* the image RGB-converted and ``thumbnail((n, n))``-ed with ``n = settings.image.longest_side_px`` (2048),
  then PNG. ``thumbnail`` only ever downscales and keeps the aspect ratio, so a smaller page is sent as it
  is (unlike LightOnOCR-2's forced size);
* ``chat_template_kwargs`` from the preset with every request (thinking off).

The largest prompt a page can take (``max_prompt_tokens``, for the repair pass's context check) follows the reference
script uv-scripts/ocr ``lighton-ocr3-saturate.py`` at e2b0aa5: 16-px patches merged 2 x 2, so a 2048-px page is at most
64 x 64 = 4,096 image tokens, plus 64 tokens for the text around the image.
"""
from __future__ import annotations

import base64
from typing import Any, ClassVar

from . import ChatAdapter, data_url, png_bytes

#: pixels per image token along each side: 16-px patches merged 2 x 2 (the reference script's ``SERVING["patch"]``)
PATCH = 32
#: tokens for the chat template and text around the image (the reference script's margin in its context check)
PROMPT_MARGIN = 64


def png_thumbnail(image: bytes, longest: int) -> tuple[str, tuple[int, int]]:
    """RGB, ``thumbnail((longest, longest))`` (downscale only, Pillow's default filter), base64 PNG; and the size."""
    from ..images.pixels import rgb_image

    img = rgb_image(image)
    img.thumbnail((longest, longest))
    return png_bytes(img), img.size


class LightOnOCR3Adapter(ChatAdapter):
    adapter: ClassVar[str] = "lighton-ocr-3"

    @property
    def target_longest(self) -> int:
        return int(self.config["image"]["longest_side_px"])

    @property
    def chat_template_kwargs(self) -> dict[str, Any]:
        return dict(self.config.get("chat_template_kwargs") or {})

    def max_prompt_tokens(self) -> int:
        """A square page at the longest side: ``ceil(longest / PATCH)`` squared image tokens, plus the margin."""
        side = -(-self.target_longest // PATCH)
        return side * side + PROMPT_MARGIN

    def request(self, image: bytes) -> dict:
        b64, _ = png_thumbnail(image, self.target_longest)
        return self._body(b64)

    def request_region(self, crop: bytes, region=None, t=None) -> dict:
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
