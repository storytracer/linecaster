"""Image step engines: the working image (lossless WebP), and image conversion to JPEG, JPEG 2000, PNG or WebP with
GPU decoding and encoding where the machine has it."""
from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..images.convert import to_working_webp
from .base import RuleEngine


class WebpLosslessImageEngine(RuleEngine):
    """Converts a page image into the working image, lossless WebP at full resolution.

    ``linecaster.images.convert.to_working_webp``: any Pillow-supported page image decoded, 8-bit sRGB with its ICC
    profile applied, encoded as lossless WebP at full resolution (method 0, exact). Pages over WebP's or Pillow's size
    limit raise ``ImageTooLarge`` before decoding. Takes the page image's bytes and returns the WebP bytes with their
    record (size, hashes, decoder).

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "image.webp-lossless.v1"
    step = "image"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["image"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        effort: int = Field(80, ge=0, le=100, description="libwebp's lossless compression effort (Pillow's "
                                                          "quality): size and speed, never pixels")

    def extension(self) -> str:
        """The converted image's file extension."""
        return "webp"

    def __call__(self, data: bytes, **options) -> tuple[bytes, dict[str, Any]]:
        return to_working_webp(data, effort=self.configured(options).effort)


class ImageConvertEngine(RuleEngine):
    """Converts a page image into JPEG, JPEG 2000, PNG or WebP at full resolution, 8-bit sRGB
    (``linecaster.images.transcode``): the working image's colour handling (the ICC profile to sRGB, 16 to 8 bit,
    alpha onto white), the size limit before decoding, image warnings recorded.

    Decoding runs on a GPU for JPEG, JPEG 2000 and TIFF in 8-bit gray or RGB, encoding on a GPU for JPEG and JPEG 2000,
    wherever the machine has an NVIDIA GPU and nvImageCodec (``linecaster[nvimgcodec]``); everything else, and every
    image on a machine without them, with Pillow. ``accel`` forces either side. Each image's record names its decoder
    and encoder. ``decode`` and ``encode`` are the two steps (a block runs them as stages with windows of their own);
    calling the engine does both.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "image.convert.v1"
    step = "image"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["image"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        format: Literal["jpg", "jp2", "png", "webp"] = Field(description="the output format")
        quality: int = Field(80, ge=0, le=100, description="jpg, webp: the encoder's quality, 0 to 100")
        lossless: bool = Field(False, description="webp: lossless WebP; jp2: the reversible wavelet (else psnr)")
        psnr: float | None = Field(None, gt=0, description="jp2 without lossless: the target PSNR in dB")
        method: int = Field(4, ge=0, le=6, description="webp: libwebp's effort, 0 (fast) to 6 (small)")
        compress_level: int = Field(6, ge=0, le=9, description="png: zlib's level, 0 to 9")
        accel: Literal["auto", "gpu", "cpu"] = Field("auto", description="auto: decode and encode on a GPU where "
                                                     "the machine has one and it supports the format, else on the "
                                                     "CPU; gpu: an error where it cannot; cpu: never the GPU")

        @model_validator(mode="after")
        def _jp2(self):
            if self.format == "jp2" and not self.lossless and self.psnr is None:
                raise ValueError("jp2: lossless, or a psnr")
            return self

    def settings(self, options: dict | None = None) -> dict[str, Any]:
        """The encoder's settings for ``linecaster.images.transcode.encode``."""
        o = self.configured(options or {})
        return {"quality": o.quality, "lossless": o.lossless, "psnr": o.psnr, "method": o.method,
                "compress_level": o.compress_level}

    def extension(self) -> str:
        """The converted image's file extension."""
        return self.options.format

    def decode(self, data: bytes, device: int = 0, **options):
        """The image decoded to 8-bit sRGB (``linecaster.images.transcode.decode``)."""
        from ..images.transcode import decode

        return decode(data, self.configured(options).accel, device)

    def encode(self, decoded, device: int = 0, **options) -> tuple[bytes, dict[str, Any]]:
        """``(bytes, record)``: the decoded image encoded (``linecaster.images.transcode.encode`` and ``record``)."""
        from ..images.transcode import encode, record

        o = self.configured(options)
        out, encoder = encode(decoded.rgb, o.format, accel=o.accel, device=device, **self.settings(options))
        return out, record(decoded, out, o.format, encoder)

    def __call__(self, data: bytes, device: int = 0, **options) -> tuple[bytes, dict[str, Any]]:
        return self.encode(self.decode(data, device, **options), device, **options)
