"""Image conversion: any Pillow-readable page image to the working image (lossless WebP, 8-bit sRGB).

Pure functions, no datatrove; blocks wrap them. Nothing oversized is decoded: the size is checked
from the header first (``Image.open`` reads only the header).

Size limit (all three must hold):

* width <= 16,383 and height <= 16,383 (WebP's hard limit);
* width x height <= 2 x ``PIL.Image.MAX_IMAGE_PIXELS`` (the threshold above which Pillow refuses to
  open an image as a decompression bomb). The value is read at call time and never changed here;
  with ``MAX_IMAGE_PIXELS = None`` there is no pixel-count limit.

Color conversion to 8-bit sRGB RGB (see ``docs/reference/serialization.md``):

* an embedded ICC profile is applied with LittleCMS (perceptual intent) to sRGB;
* 16-bit grayscale is scaled to 8 bits (``round(v * 255 / 65535)``); Pillow itself already reads
  16-bit-per-channel RGB as 8-bit RGB;
* grayscale, bilevel and palette images become RGB (channels replicated / palette expanded);
* alpha is composited onto white (OCR wants opaque pages); CMYK without a profile uses Pillow's
  plain conversion;
* EXIF orientation is NOT applied (coordinates refer to the stored pixel grid); it is reported.

The output is always lossless WebP (``lossless=True, method=0, exact=True``) at full resolution.
"""
from __future__ import annotations

import hashlib
import io
import warnings
from typing import Any

import numpy as np
import PIL
from PIL import Image, ImageCms, features

WEBP_MAX_DIMENSION = 16383

_SOURCE_LIBS = {"JPEG": "libjpeg_turbo", "JPEG2000": "jpg_2000", "TIFF": "libtiff", "PNG": "zlib",
                "WEBP": "webp"}
_LIB_NAMES = {"libjpeg_turbo": "libjpeg-turbo", "jpg_2000": "OpenJPEG", "libtiff": "libtiff",
              "zlib": "zlib", "webp": "libwebp"}


class ImageTooLarge(ValueError):
    """The page is over the size limit; ``reason`` says which limit."""

    def __init__(self, reason: str, width: int | None = None, height: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.width = width
        self.height = height


def max_pixels() -> int | None:
    """The pixel-count limit: 2 x ``PIL.Image.MAX_IMAGE_PIXELS`` as it is now (None = no limit)."""
    m = Image.MAX_IMAGE_PIXELS
    return None if m is None else 2 * int(m)


def check_size(width: int, height: int) -> str | None:
    """A reject reason when ``width x height`` is over the limit, else None."""
    if width > WEBP_MAX_DIMENSION:
        return f"width {width} px exceeds WebP's limit of {WEBP_MAX_DIMENSION} px"
    if height > WEBP_MAX_DIMENSION:
        return f"height {height} px exceeds WebP's limit of {WEBP_MAX_DIMENSION} px"
    limit = max_pixels()
    if limit is not None and width * height > limit:
        return (f"{width} x {height} = {width * height} pixels exceeds 2 x PIL.Image.MAX_IMAGE_PIXELS"
                f" = {limit}")
    return None


def _open(data: bytes) -> Image.Image:
    """Open from the header only; Pillow's own bomb error becomes ``ImageTooLarge``."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            return Image.open(io.BytesIO(data))
    except Image.DecompressionBombError as e:
        # Pillow's open-time threshold is the same 2 x MAX_IMAGE_PIXELS this module enforces
        raise ImageTooLarge(f"pixel count exceeds 2 x PIL.Image.MAX_IMAGE_PIXELS = {max_pixels()}"
                            f" (Pillow: {e})") from e


def read_header(data: bytes) -> tuple[str | None, int, int]:
    """``(format, width, height)`` from the image header, without decoding pixels."""
    im = _open(data)
    return im.format, im.width, im.height


def decoder_string(source_format: str | None = None) -> str:
    """e.g. ``"Pillow 13.0.0 / OpenJPEG 2.5.4 / libwebp 1.6.0"``."""
    parts = [f"Pillow {PIL.__version__}"]
    lib = _SOURCE_LIBS.get(source_format or "")
    if lib and lib != "webp":
        v = features.version(lib)
        if v:
            parts.append(f"{_LIB_NAMES[lib]} {v}")
    parts.append(f"libwebp {features.version('webp')}")
    return " / ".join(parts)


def _to_8bit(im: Image.Image) -> Image.Image:
    """Bring high-bit-depth single-channel modes to 8-bit ``L``."""
    if im.mode.startswith("I;16") or im.mode == "I":
        a = np.asarray(im).astype(np.int64)
        if im.mode == "I" and a.size and a.max() <= 255 and a.min() >= 0:
            out = a
        else:
            out = (np.clip(a, 0, 65535) * 255 + 32767) // 65535
        return Image.fromarray(out.astype(np.uint8), "L")
    if im.mode == "F":
        a = np.asarray(im)
        return Image.fromarray(np.clip(np.rint(a), 0, 255).astype(np.uint8), "L")
    return im


def to_srgb(im: Image.Image) -> tuple[Image.Image, dict[str, Any]]:
    """Convert a decoded image to 8-bit sRGB ``RGB``; returns the image and what was done."""
    notes: dict[str, Any] = {"source_mode": im.mode, "icc_applied": False, "alpha_flattened": False}
    icc = im.info.get("icc_profile")
    im = _to_8bit(im)
    if im.mode == "1":
        im = im.convert("L")
    if im.mode == "P":
        im = im.convert("RGBA" if "transparency" in im.info else "RGB")
    if im.mode in ("PA",):
        im = im.convert("RGBA")
    alpha = None
    if im.mode in ("RGBA", "LA", "La", "RGBa"):
        if im.mode == "La":
            im = im.convert("LA")
        if im.mode == "RGBa":
            im = im.convert("RGBA")
        alpha = im.getchannel("A")
        im = im.convert("RGB" if im.mode == "RGBA" else "L")
    if icc:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            dst = ImageCms.createProfile("sRGB")
            in_mode = im.mode if im.mode in ("RGB", "L", "CMYK") else None
            if in_mode is not None:
                im = ImageCms.profileToProfile(im, src, dst, renderingIntent=ImageCms.Intent.PERCEPTUAL,
                                               outputMode="RGB")
                notes["icc_applied"] = True
        except (ImageCms.PyCMSError, OSError, ValueError) as e:
            notes["icc_error"] = str(e)
    if im.mode != "RGB":
        im = im.convert("RGB")
    if alpha is not None:
        if alpha.getextrema() != (255, 255):
            white = Image.new("RGB", im.size, (255, 255, 255))
            white.paste(im, mask=alpha)
            im = white
            notes["alpha_flattened"] = True
    return im, notes


def to_working_webp(data: bytes, *, effort: int = 80) -> tuple[bytes, dict[str, Any]]:
    """Decode any Pillow-supported image and encode it as lossless WebP at full resolution.

    ``effort`` is libwebp's lossless compression effort (Pillow's ``quality`` for lossless; 80 is
    Pillow's default). It changes size and speed, never pixels: on a 24 MP newspaper scan, 0 encoded
    in 1.7 s to 17.2 MB, 80 in 7.0 s to 16.6 MB (one measurement, on an aarch64 machine, NOTES.md; see
    docs/reference/serialization.md).

    Raises ``ImageTooLarge`` (with ``reason``) before decoding when the page is over the limit.
    ``info`` keys: ``format`` (``"webp"``), ``width``, ``height``, ``source_format``, ``source_mode``,
    ``pixels_sha256`` (of the decoded 8-bit RGB pixels, row-major), ``sha256`` (of the WebP bytes),
    ``decoder``, ``icc_applied``, ``alpha_flattened`` and, when present, ``exif_orientation``.
    """
    im = _open(data)
    reason = check_size(im.width, im.height)
    if reason:
        raise ImageTooLarge(reason, im.width, im.height)
    source_format = im.format
    orientation = None
    try:
        orientation = im.getexif().get(0x0112)
    except Exception:       # a broken EXIF block must not stop the conversion
        orientation = None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        im.load()
    rgb, notes = to_srgb(im)
    pixels = rgb.tobytes()
    buf = io.BytesIO()
    rgb.save(buf, format="WEBP", lossless=True, method=0, exact=True, quality=effort)
    out = buf.getvalue()
    info: dict[str, Any] = {
        "format": "webp",
        "width": rgb.width,
        "height": rgb.height,
        "source_format": source_format.lower() if source_format else None,
        "pixels_sha256": hashlib.sha256(pixels).hexdigest(),
        "sha256": hashlib.sha256(out).hexdigest(),
        "decoder": decoder_string(source_format),
        "webp_settings": {"lossless": True, "method": 0, "exact": True, "quality": effort},
        **notes,
    }
    if orientation and orientation != 1:
        info["exif_orientation"] = int(orientation)
    return out, info
