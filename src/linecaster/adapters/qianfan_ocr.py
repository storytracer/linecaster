"""Adapter ``qianfan-ocr``: baidu/Qianfan-OCR (preset ``qianfan-ocr``).

* message = the page image, then ``settings.prompt`` (image before text, the card's order);
* the image bytes sent as they are, no resize and no conversion, with the media type sniffed from the
  magic bytes (JPEG, PNG, TIFF, WebP; anything else is an error): the processor
  tiles and RGB-converts itself;
* ``settings.chat_template_kwargs`` with every request (Layout-as-Thought off).
"""
from __future__ import annotations

import base64
from typing import Any, ClassVar

from . import ChatAdapter

#: magic bytes -> media type (WebP checked separately)
MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)


def sniff_mime(raw: bytes) -> str:
    """The media type of an encoded image from its magic bytes."""
    for prefix, mime in MAGIC:
        if raw.startswith(prefix):
            return mime
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError(f"unrecognized image magic bytes: {raw[:8]!r}")


class QianfanOCRAdapter(ChatAdapter):
    adapter: ClassVar[str] = "qianfan-ocr"

    @property
    def chat_template_kwargs(self) -> dict[str, Any]:
        return dict(self.config.get("chat_template_kwargs") or {})

    def request(self, image: bytes) -> dict:
        from ..images import drop_damaged_png_chunks

        image = drop_damaged_png_chunks(image)            # the server's decoder refuses a damaged PNG chunk too
        url = f"data:{sniff_mime(image)};base64," + base64.b64encode(image).decode()
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": url}},
                {"type": "text", "text": self.prompt},
            ]}],
            **self.sampling,
            "chat_template_kwargs": self.chat_template_kwargs,
        }

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "prompt": self.prompt, "chat_template_kwargs": self.chat_template_kwargs,
                "image": {"resize": None, "bytes": "as received, media type sniffed"}}
