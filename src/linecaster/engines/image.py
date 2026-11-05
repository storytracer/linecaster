"""Image step engines: the working image."""
from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from ..images.convert import to_working_webp
from .base import RuleEngine


class WebpLosslessImageEngine(RuleEngine):
    """The working image (``linecaster.images.convert.to_working_webp``): any Pillow-supported page image
    decoded, 8-bit sRGB with its ICC profile applied, encoded as lossless WebP at full resolution (method 0,
    exact). Pages over WebP's or Pillow's size limit raise ``ImageTooLarge`` before decoding. Takes the page
    image's bytes and returns the WebP bytes with their record (size, hashes, decoder)."""

    engine_id: ClassVar[str] = "image.webp-lossless.v1"
    step = "image"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["image"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        effort: int = Field(80, ge=0, le=100, description="libwebp's lossless compression effort (Pillow's "
                                                          "quality): size and speed, never pixels")

    def __call__(self, data: bytes, **options) -> tuple[bytes, dict[str, Any]]:
        return to_working_webp(data, effort=self.configured(options).effort)
