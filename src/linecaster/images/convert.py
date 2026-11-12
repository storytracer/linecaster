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

Image warnings: a fault an image is read around is a warning, not an error, and is reported (``warnings``): a PNG
whose optional (ancillary) chunk, e.g. its ICC profile (``iCCP``) or text, fails its checksum is read without that chunk
(``open_image``), as libpng and browsers read it (Pillow alone refuses the whole file); what Pillow warns about while
reading (e.g. corrupt EXIF), EXIF that cannot be read and an ICC profile that cannot be applied are reported too. A
fault that keeps the pixels from being read (a damaged header or palette, a truncated file) is an error.

The output is always lossless WebP (``lossless=True, method=0, exact=True``) at full resolution.
"""
from __future__ import annotations

import hashlib
import io
import struct
import warnings
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
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


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_chunks(data: bytes) -> tuple[bytes, list[str]]:
    """(``data`` without a PNG's damaged ancillary chunks, their types); ``data`` itself and [] when none."""
    if not data.startswith(PNG_SIGNATURE):
        return data, []
    keep, i, dropped = [data[:8]], 8, []
    while i + 12 <= len(data):
        n = struct.unpack(">I", data[i:i + 4])[0]
        end = i + 12 + n
        if end > len(data):
            break
        kind = data[i + 4:i + 8]
        if kind[0] & 32 and zlib.crc32(data[i + 4:end - 4]) != struct.unpack(">I", data[end - 4:end])[0]:
            dropped.append(kind.decode("latin-1"))            # ancillary, checksum wrong: left out
        else:
            keep.append(data[i:end])
        i = end
        if kind == b"IEND":
            break
    if not dropped:
        return data, []
    keep.append(data[i:])
    return b"".join(keep), dropped


def drop_damaged_png_chunks(data: bytes) -> bytes:
    """``data`` without the ancillary chunks of a PNG whose checksum is wrong (a chunk whose type starts with a
    lowercase letter: ICC profile, text, time, ...), as libpng skips them; anything else unchanged, the same object
    when nothing is dropped. Critical chunks and a truncated end are left as they are, for Pillow to refuse.

    Args:
        data: the image file's bytes.
    """
    return _png_chunks(data)[0]


def _damaged_note(dropped: list[str]) -> str:
    return f"damaged PNG chunks, left out when read: {', '.join(dropped)}"


@contextmanager
def _warnings_into(out: list[str] | None) -> Iterator[None]:
    """Pillow's warnings in the block, as text, into ``out`` (None: dropped); never the bomb warning (the size limit
    is checked on its own, ``check_size``). ``warnings.catch_warnings`` is process-wide: across threads a warning may
    land in another image's list."""
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        yield
    if out is not None:
        out.extend(f"{w.category.__name__}: {w.message}" for w in seen)


def open_image(data: bytes, warnings: list[str] | None = None) -> Image.Image:
    """``Image.open`` of the bytes (the header only, pixels on demand), with a PNG's damaged ancillary chunks left
    out (``drop_damaged_png_chunks``).

    Args:
        data: the image file's bytes.
        warnings: a list the image warnings found while opening are appended to (the chunks left out, what Pillow
            warns about); None: not collected.
    """
    clean, dropped = _png_chunks(data)
    if dropped and warnings is not None:
        warnings.append(_damaged_note(dropped))
    with _warnings_into(warnings):
        return Image.open(io.BytesIO(clean))


def image_warnings(data: bytes) -> list[str]:
    """Reads an image as a check and returns its image warnings (``open_image``; EXIF that cannot be read; what Pillow
    warns about while verifying the file): faults it is read around. Raises on a fault that keeps it from being read
    (Pillow's error), as ``Image.verify`` does.

    Args:
        data: the image file's bytes.
    """
    out: list[str] = []
    with open_image(data, out) as im, _warnings_into(out):
        try:
            im.getexif()
        except Exception as e:  # noqa: BLE001 - metadata only: the pixels can still be read
            out.append(f"EXIF not readable: {type(e).__name__}: {e}")
    with open_image(data) as im, _warnings_into(out):
        im.verify()
    return out


def _open(data: bytes, found: list[str] | None = None) -> Image.Image:
    """Open from the header only; Pillow's own bomb error becomes ``ImageTooLarge``."""
    try:
        return open_image(data, found)
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
    ``decoder``, ``icc_applied``, ``alpha_flattened`` and, when present, ``exif_orientation``, ``icc_error`` and
    ``warnings`` (the image warnings: faults read around, see the module docstring).
    """
    found: list[str] = []
    im = _open(data, found)
    reason = check_size(im.width, im.height)
    if reason:
        raise ImageTooLarge(reason, im.width, im.height)
    source_format = im.format
    orientation = None
    with _warnings_into(found):
        try:
            orientation = im.getexif().get(0x0112)
        except Exception as e:  # noqa: BLE001 - a broken EXIF block must not stop the conversion
            found.append(f"EXIF not readable: {type(e).__name__}: {e}")
            orientation = None
        im.load()
        rgb, notes = to_srgb(im)
    if "icc_error" in notes:
        found.append(f"ICC profile not applied: {notes['icc_error']}")
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
    if found:
        info["warnings"] = found
    return out, info
