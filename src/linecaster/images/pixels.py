"""Page images as engines receive them: plain 8-bit RGB pixels, decoded once per page and process, on an NVIDIA GPU
where the machine has one (``linecaster.images.accel``), else with Pillow.

Plain pixels are Pillow's ``convert("RGB")`` of the file as it opens: no ICC profile applied, no EXIF orientation, a
16-bit gray image clipped as Pillow does. A GPU decodes JPEG, JPEG 2000 and TIFF in 8-bit gray or RGB
(``transcode.gpu_decodable``) to the same layout (gray repeated into three channels, as ``convert`` does); every other
image is Pillow's. A GPU and Pillow can round a lossy image's pixels differently (by a few levels of 255), so every
decode names its decoder (``Pixels.decoder``), which the steps record (measurement ``decoder``). An image a GPU decoder
refuses, or a GPU that fails, is decoded with Pillow (``Pixels.fallback``: ``refused``, ``error: ...``); with ``accel``
``gpu`` either is an error.

``accel`` and the CUDA device come from the call, else from the process's choice (``set_decoding``), which linecaster's
model blocks set from their ``image_decode`` (``--image-decode``) and the worker's GPU. A process decodes a page once:
the last ``KEPT`` decodes are kept by the bytes object they came from (a page's ``media_bytes``, the same object for
every block a page passes in a task), so the blocks after the first that needs the image use the same pixels, which are
read-only. ``decodes()`` counts the files actually decoded; ``last_decode()`` is the calling thread's last decode (kept or
new), which a block that hands the bytes to code that decodes them (a chat adapter) reads afterwards.
"""
from __future__ import annotations

import contextlib
import threading
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np
from loguru import logger

from . import accel as hw

#: how many decoded pages a process keeps: a page passes all of a task's in-process blocks before the next is read, so
#: a few are enough; each is its RGB size (36 MB for 12 megapixels)
KEPT = 4


@dataclass(frozen=True)
class Pixels:
    """A decoded page image: ``rgb`` (height x width x 3, uint8, read-only) and what decoded it."""

    rgb: np.ndarray
    decoder: str                      # e.g. "nvImageCodec 0.10.0 (GPU 0)", "Pillow 12.0.0 / OpenJPEG 2.5.4"
    fallback: str | None = None       # why a GPU did not: "refused", "error: ..."
    accel: str = "auto"

    @property
    def gpu(self) -> bool:
        return "(GPU" in self.decoder


def set_decoding(accel: str | None = None, device: int | None = None) -> None:
    """This process's choice where a call names none: ``accel`` (``auto``, ``gpu``, ``cpu``) and the CUDA device."""
    if accel is not None:
        if accel not in hw.ACCEL:
            raise ValueError(f"image decode {accel!r}: one of {', '.join(hw.ACCEL)}")
        _SETTING["accel"] = accel
    if device is not None:
        _SETTING["device"] = int(device)


def decoding() -> tuple[str, int]:
    """This process's choice: ``(accel, device)``."""
    return _SETTING["accel"], _SETTING["device"]


def decode_pixels(data: bytes, accel: str | None = None, device: int | None = None) -> Pixels:
    """The page image's plain RGB pixels and decoder (module docstring), decoded once per process.

    Args:
        data: the image file's bytes.
        accel: ``auto``, ``gpu`` or ``cpu``; default the process's (``set_decoding``).
        device: the CUDA device; default the process's.
    """
    accel = accel or _SETTING["accel"]
    with _LOCK:
        kept = _KEPT.get(id(data))
        if kept is not None and kept[0] is data and kept[1].accel == accel:       # the same bytes object: the page
            _KEPT.move_to_end(id(data))
            _LAST.decode = (kept[1], False)
            return kept[1]
    px = _decode(data, accel, _SETTING["device"] if device is None else device)
    with _LOCK:
        _COUNT[0] += 1
        _KEPT[id(data)] = (data, px)
        while len(_KEPT) > KEPT:
            _KEPT.popitem(last=False)
    _LAST.decode = (px, True)
    return px


def decode_rgb(data: bytes, accel: str | None = None, device: int | None = None) -> np.ndarray:
    """``decode_pixels(...).rgb``: the RGB array every engine backend receives."""
    return decode_pixels(data, accel, device).rgb


def rgb_image(data: bytes):
    """The page image as a Pillow RGB image of its plain pixels (``decode_pixels``), for code that resizes or encodes
    it (a chat adapter's request); the same as ``open_image(data).convert("RGB")`` where Pillow decodes it."""
    from PIL import Image

    return Image.fromarray(decode_rgb(data), "RGB")


def last_decode() -> tuple[Pixels, bool] | None:
    """The calling thread's last decode (``decode_pixels``) and whether it decoded the file (False: a kept page), or
    None since ``forget_last``."""
    return getattr(_LAST, "decode", None)


def forget_last() -> None:
    _LAST.decode = None


def decodes() -> int:
    """How many image files this process has decoded (not counting the pages it kept)."""
    return _COUNT[0]


def _decode(data: bytes, accel: str, device: int) -> Pixels:
    from .convert import open_image
    from .transcode import _PILLOW_JP2, gpu_decodable, pillow_codec

    with open_image(data) as im:
        fallback = None
        if hw.use_gpu(accel, gpu_decodable(im)):
            codec = None
            try:
                codec = hw.gpu_codec(device)
                a = codec.decode(data, gray=im.mode == "L")
            except Exception as e:  # the GPU failed (not the file): Pillow decodes it, and it is said
                if accel == "gpu":
                    raise
                a, fallback = None, f"error: {type(e).__name__}: {str(e)[:200]}"
                if fallback not in _SAID:
                    _SAID.add(fallback)
                    logger.warning("GPU image decoding failed, Pillow decodes instead: {error}", error=fallback[7:])
            if a is not None and a.shape[:2] == (im.height, im.width):
                rgb = np.repeat(a[..., None], 3, axis=2) if a.ndim == 2 else np.ascontiguousarray(a)
                rgb.setflags(write=False)
                return Pixels(rgb, f"{codec.version} (GPU {device})", None, accel)
            if accel == "gpu":
                raise RuntimeError(f"image decode gpu: no GPU decoder took this {im.format} image")
            fallback = fallback or "refused"
        with _PILLOW_JP2 if im.format == "JPEG2000" else contextlib.nullcontext():
            rgb = np.asarray(im.convert("RGB"))
        rgb.setflags(write=False)
        return Pixels(rgb, pillow_codec(im.format), fallback, accel)


_SETTING: dict = {"accel": "auto", "device": 0}
_KEPT: OrderedDict[int, tuple[bytes, Pixels]] = OrderedDict()
_LOCK = threading.Lock()
_COUNT = [0]
_LAST = threading.local()
_SAID: set[str] = set()
