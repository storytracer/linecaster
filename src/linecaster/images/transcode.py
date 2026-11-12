"""Image conversion: any image Pillow reads to JPEG, JPEG 2000, PNG or WebP, decoded and encoded on a GPU where the
machine has one and it supports the format (``linecaster.images.accel``), else on the CPU with Pillow.

Two steps, so a pipeline can run them in stages of their own (``linecaster.blocks.conversion.images``):

* ``decode``: the image's header (Pillow, no pixels), the size limit (``convert.check_size``), its EXIF orientation
  (reported, not applied), then the pixels: on the GPU for JPEG, JPEG 2000 and TIFF in 8-bit ``L`` or ``RGB``
  (nvJPEG, nvJPEG2000, nvTIFF), else with Pillow (one JPEG 2000 image at a time per process: Pillow's JPEG 2000
  decoder holds the GIL throughout, so only processes decode those in parallel). Either way the pixels then go through the working image's colour
  handling (``convert.to_srgb``: the ICC profile to sRGB, 16 to 8 bit, alpha onto white): a GPU decode hands it the
  source's own mode with the profile read from the header, so both paths share every step after the decoder.
* ``encode``: the 8-bit sRGB pixels as ``jpg`` (``quality``), ``jp2`` (``lossless``, else ``psnr``), ``png``
  (``compress_level``) or ``webp`` (``quality``, ``lossless``, ``method``), full resolution. JPEG and JPEG 2000 are
  encoded on the GPU where it can (nvJPEG, nvJPEG2000); PNG and WebP always with Pillow (libpng/zlib, libwebp): no
  GPU library writes them.

Whatever keeps a GPU from doing an image (its decoder or encoder rejects the file, or the GPU fails: an error, too
little memory) the CPU does it instead, recorded as ``gpu_fallback`` (``{"decode": "refused" or "error: ..."}``, the
same for ``encode``); ``accel`` ``gpu`` makes either an error. Each image records what decoded and what encoded it
(``decoder``, ``encoder``), since a GPU and a CPU decoder can
round differently (a lossy JPEG's IDCT and upsampling, a lossy JPEG 2000's wavelet): ``compare_decoders`` measures
the difference on given images. ``accel`` (``auto``, ``gpu``, ``cpu``) chooses per step; ``auto`` takes the GPU where
it can.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import threading
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import PIL
from PIL import Image, features

from . import accel as hw
from .convert import ImageTooLarge, _open, _warnings_into, check_size, to_srgb

#: the output formats: linecaster's name -> (Pillow's format, file extension)
FORMATS = {"jpg": ("JPEG", "jpg"), "jp2": ("JPEG2000", "jp2"), "png": ("PNG", "png"), "webp": ("WEBP", "webp")}
#: the source modes a GPU decoder hands over as they are: 8-bit gray and RGB (other modes: Pillow)
GPU_MODES = frozenset({"L", "RGB"})
#: Pillow decodes one JPEG 2000 image at a time per process: its decoder reads through Python (``pulls_fd``) and holds
#: the GIL for the whole decode, so a second one in parallel gains nothing and only allocates OpenJPEG's buffers
#: (4 bytes a sample) early; the threads waiting here hold only the file's bytes. Processes decode in parallel.
_PILLOW_JP2 = threading.Lock()

_PILLOW_LIBS = {"JPEG": ("libjpeg_turbo", "libjpeg-turbo"), "JPEG2000": ("jpg_2000", "OpenJPEG"),
                "TIFF": ("libtiff", "libtiff"), "PNG": ("zlib", "zlib"), "WEBP": ("webp", "libwebp")}


def pillow_codec(fmt: str | None) -> str:
    """Pillow and the library behind ``fmt`` (Pillow's format name), e.g. ``"Pillow 13.0.0 / OpenJPEG 2.5.4"``."""
    parts = [f"Pillow {PIL.__version__}"]
    lib = _PILLOW_LIBS.get(fmt or "")
    if lib and (v := features.version(lib[0])):
        parts.append(f"{lib[1]} {v}")
    return " / ".join(parts)


@dataclass
class Decoded:
    """An image decoded to 8-bit sRGB (``rgb``), with what ``decode`` found out."""

    rgb: Image.Image
    source_format: str | None
    source_mode: str
    decoder: str
    notes: dict[str, Any] = field(default_factory=dict)       # icc_applied, alpha_flattened, icc_error, gpu_fallback
    exif_orientation: int | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def pixels(self) -> int:
        return self.rgb.width * self.rgb.height


def _header(data: bytes, found: list[str]) -> Image.Image:
    im = _open(data, found)
    if reason := check_size(im.width, im.height):
        raise ImageTooLarge(reason, im.width, im.height)
    return im


def _orientation(im: Image.Image, found: list[str]) -> int | None:
    with _warnings_into(found):
        try:
            value = im.getexif().get(0x0112)
        except Exception as e:  # noqa: BLE001 - metadata only
            found.append(f"EXIF not readable: {type(e).__name__}: {e}")
            return None
    return int(value) if value and value != 1 else None


def gpu_decodable(im: Image.Image) -> bool:
    """Whether a GPU decoder takes the image (its header): JPEG, JPEG 2000 or TIFF, 8-bit gray or RGB."""
    return im.format in hw.GPU_DECODE_FORMATS and im.mode in GPU_MODES


def decode(data: bytes, accel: str = "auto", device: int = 0) -> Decoded:
    """Decodes an image to 8-bit sRGB (module docstring). Raises ``ImageTooLarge`` before decoding a page over the
    limit, Pillow's error for an image it cannot read.

    Args:
        data: the image file's bytes.
        accel: ``auto``, ``gpu`` or ``cpu`` (``linecaster.images.accel.ACCEL``).
        device: the CUDA device for a GPU decode.
    """
    found: list[str] = []
    im = _header(data, found)
    fmt, mode, orientation = im.format, im.mode, _orientation(im, found)
    decoder = None
    fallback = None
    if hw.use_gpu(accel, gpu_decodable(im)):
        try:
            codec = hw.gpu_codec(device)
            pixels = codec.decode(data, gray=mode == "L")
        except Exception as e:  # noqa: BLE001 - the GPU failed (not the file): Pillow decodes it, and it is said
            if accel == "gpu":
                raise
            pixels, fallback = None, f"error: {type(e).__name__}: {str(e)[:200]}"
        if pixels is not None and pixels.shape[:2] == (im.height, im.width):
            gpu = Image.fromarray(np.ascontiguousarray(pixels), mode)
            if "icc_profile" in im.info:
                gpu.info["icc_profile"] = im.info["icc_profile"]
            im, decoder = gpu, f"{codec.version} (GPU {device})"
        elif accel == "gpu":
            raise RuntimeError(f"accel gpu: no GPU decoder took this {fmt} image")
        else:
            fallback = fallback or "refused"
    if decoder is None:
        with _warnings_into(found), (_PILLOW_JP2 if fmt == "JPEG2000" else contextlib.nullcontext()):
            im.load()
        decoder = pillow_codec(fmt)
    with _warnings_into(found):
        rgb, notes = to_srgb(im)
    if "icc_error" in notes:
        found.append(f"ICC profile not applied: {notes['icc_error']}")
    notes.pop("source_mode", None)
    if fallback:
        notes["gpu_fallback"] = {"decode": fallback}
    return Decoded(rgb, fmt.lower() if fmt else None, mode, decoder, notes, orientation, found)


def encode(rgb: Image.Image, fmt: str, *, quality: int = 80, lossless: bool = False, psnr: float | None = None,
           method: int = 4, compress_level: int = 6, accel: str = "auto", device: int = 0,
           notes: dict | None = None) -> tuple[bytes, str]:
    """``(bytes, encoder)``: 8-bit sRGB pixels encoded as ``fmt`` at full resolution (module docstring).

    Args:
        rgb: the pixels, an 8-bit ``RGB`` image.
        fmt: ``jpg``, ``jp2``, ``png`` or ``webp``.
        quality: ``jpg``, ``webp``: 0 to 100 (libwebp's ``quality``; libjpeg's, with 4:2:0 chroma and optimized
            Huffman tables).
        lossless: ``webp``: lossless WebP; ``jp2``: the reversible wavelet (else ``psnr``).
        psnr: ``jp2`` without ``lossless``: the target PSNR in dB.
        method: ``webp``: libwebp's effort, 0 (fast) to 6 (small).
        compress_level: ``png``: zlib's level, 0 to 9.
        accel: ``auto``, ``gpu`` or ``cpu`` (``jpg`` and ``jp2`` only; PNG and WebP are encoded on the CPU).
        device: the CUDA device for a GPU encode.
        notes: where a GPU encode that fell back to Pillow is said (``gpu_fallback``: ``{"encode": "refused" or
            "error: ..."}``).
    """
    if fmt not in FORMATS:
        raise ValueError(f"format {fmt!r}: one of {', '.join(FORMATS)}")
    if fmt == "jp2" and not lossless and psnr is None:
        raise ValueError("jp2: lossless, or a psnr")
    if hw.use_gpu(accel if fmt in hw.GPU_ENCODE_FORMATS else "cpu", fmt in hw.GPU_ENCODE_FORMATS):
        params = {"quality": quality} if fmt == "jpg" else {"lossless": lossless, "psnr": psnr}
        try:
            codec = hw.gpu_codec(device)
            out, why = codec.encode(np.asarray(rgb), fmt, params), "refused"
        except Exception as e:  # noqa: BLE001 - the GPU failed (not the image): Pillow encodes it, and it is said
            if accel == "gpu":
                raise
            out, why = None, f"error: {type(e).__name__}: {str(e)[:200]}"
        if out is not None:
            return out, f"{codec.version} (GPU {device})"
        if accel == "gpu":
            raise RuntimeError(f"accel gpu: no GPU encoder took this image as {fmt}")
        if notes is not None:
            notes.setdefault("gpu_fallback", {})["encode"] = why
    pil_fmt = FORMATS[fmt][0]
    buf = io.BytesIO()
    if fmt == "webp":
        rgb.save(buf, "WEBP", quality=quality, lossless=lossless, method=method, exact=lossless)
    elif fmt == "jpg":
        rgb.save(buf, "JPEG", quality=quality, subsampling="4:2:0", optimize=True)
    elif fmt == "png":
        rgb.save(buf, "PNG", compress_level=compress_level)
    elif lossless:
        rgb.save(buf, "JPEG2000", irreversible=False, mct=1, no_jp2=False)
    else:
        rgb.save(buf, "JPEG2000", irreversible=True, mct=1, quality_mode="dB", quality_layers=[float(psnr)],
                 no_jp2=False)
    return buf.getvalue(), pillow_codec(pil_fmt)


def record(decoded: Decoded, out: bytes, fmt: str, encoder: str) -> dict[str, Any]:
    """The converted image's record: ``format``, ``width``, ``height``, ``bytes``, ``sha256``, ``pixels_sha256`` (of
    the decoded 8-bit RGB pixels, row-major), ``source_format``, ``source_mode``, ``decoder``, ``encoder``, the colour
    notes (``icc_applied``, ``alpha_flattened``, ``icc_error``), ``exif_orientation`` and ``warnings`` when there
    are any."""
    rgb = decoded.rgb
    info: dict[str, Any] = {"format": FORMATS[fmt][1], "width": rgb.width, "height": rgb.height, "bytes": len(out),
                            "sha256": hashlib.sha256(out).hexdigest(),
                            "pixels_sha256": hashlib.sha256(rgb.tobytes()).hexdigest(),
                            "source_format": decoded.source_format, "source_mode": decoded.source_mode,
                            "decoder": decoded.decoder, "encoder": encoder, **decoded.notes}
    if decoded.exif_orientation:
        info["exif_orientation"] = decoded.exif_orientation
    if decoded.warnings:
        info["warnings"] = list(decoded.warnings)
    return info


def convert(data: bytes, fmt: str, *, accel: str = "auto", device: int = 0, **settings) -> tuple[bytes, dict]:
    """``decode`` then ``encode`` (``settings``: its format settings): ``(bytes, record)``."""
    decoded = decode(data, accel, device)
    out, encoder = encode(decoded.rgb, fmt, accel=accel, device=device, notes=decoded.notes, **settings)
    return out, record(decoded, out, fmt, encoder)


def compare_decoders(data: bytes, device: int = 0) -> dict[str, Any]:
    """How a GPU decode of the image differs from Pillow's, after the same colour handling: ``gpu`` (whether a GPU
    decoder took it), ``max_abs`` (the largest difference of a channel value, 0-255), ``differing`` (the share of
    channel values that differ), ``mean_abs``, and both decoders.

    Args:
        data: the image file's bytes.
        device: the CUDA device.
    """
    cpu = decode(data, "cpu")
    gpu = decode(data, "auto", device)
    a, b = np.asarray(cpu.rgb, dtype=np.int16), np.asarray(gpu.rgb, dtype=np.int16)
    diff = np.abs(a - b)
    return {"gpu": gpu.decoder != cpu.decoder, "width": cpu.rgb.width, "height": cpu.rgb.height,
            "max_abs": int(diff.max()) if diff.size else 0, "mean_abs": float(diff.mean()) if diff.size else 0.0,
            "differing": float((diff > 0).mean()) if diff.size else 0.0,
            "cpu_decoder": cpu.decoder, "gpu_decoder": gpu.decoder}
