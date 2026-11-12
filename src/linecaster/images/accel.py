"""Hardware acceleration for image codecs: NVIDIA GPUs through nvImageCodec, where the machine has them.

What a machine can do is found out, never configured: ``cuda_devices`` counts the CUDA devices through the driver
(``libcuda``, present wherever an NVIDIA driver is, on aarch64 and x86_64 alike), and nvImageCodec is used when the
package is installed (``linecaster[nvimgcodec]``, its CUDA 13 wheels with nvJPEG, nvJPEG2000 and nvTIFF). Without
either, everything runs on the CPU.

On the GPU (``GPU_DECODERS``, ``GPU_ENCODERS``): decoding JPEG (nvJPEG), JPEG 2000 (nvJPEG2000) and TIFF (nvTIFF);
encoding JPEG and JPEG 2000. No GPU library writes PNG or WebP (nvImageCodec encodes them only through its CPU OpenCV
extension), so those are encoded with Pillow on the CPU. Only the GPU implementations are allowed
(``decoder_ids``/``encoder_ids``): an image nvImageCodec cannot do on the GPU comes back as None and the caller uses
Pillow, so a CPU path is always Pillow's, never another CPU library's (nvJPEG2000, for one, rejects code streams with
the vertically causal context, code-block style 0x08, and nvImageCodec logs an error for it); a GPU that fails raises,
and ``linecaster.images.transcode`` falls back to Pillow for that too.

``GpuCodec`` is one device's decoder and encoder, shared by the threads of a process: calls that arrive together are
decoded (encoded) in one batch (``Batcher``), which is how nvImageCodec keeps a GPU busy.

nvImageCodec prints nothing (``PYNVIMGCODEC_VERBOSITY=0``, set before it is imported unless the environment sets it,
e.g. ``PYNVIMGCODEC_VERBOSITY=2`` for its errors and warnings again): it logs every image a decoder rejects at ERROR
severity (``[nvjpeg2k_decoder] Could not decode jpeg2k code stream``, ``[pynvimgcodec] Something went wrong during
decoding image #0``), only verbosity 0 silences that, and the rejection is linecaster's to record
(``linecaster.images.transcode``: ``gpu_fallback``, counted). What fails beyond one image surfaces as a Python error,
which linecaster logs: a decoder or encoder that did not load is said once when a ``GpuCodec`` starts, and a GPU that
fails raises.
"""
from __future__ import annotations

import ctypes
import threading
import time
import os
from collections.abc import Callable, Sequence
from functools import cache
from typing import Any

from loguru import logger

#: nvImageCodec's verbosity unless the environment sets one: 0 prints nothing (see the module docstring)
VERBOSITY_ENV, QUIET = "PYNVIMGCODEC_VERBOSITY", "0"

#: nvImageCodec's GPU decoders (``nvidia.nvimgcodec.get_decoder_ids()``): JPEG, lossless JPEG, JPEG 2000, TIFF
GPU_DECODERS = ("nvjpeg_cuda_decoder", "nvjpeg_lossless_decoder", "nvjpeg2k_decoder", "nvtiff_cuda_decoder")
#: nvImageCodec's GPU encoders: JPEG, JPEG 2000
GPU_ENCODERS = ("nvjpeg_cuda_encoder", "nvjpeg2k_encoder")
#: the source formats (Pillow's names) a GPU decoder reads
GPU_DECODE_FORMATS = frozenset({"JPEG", "JPEG2000", "TIFF"})
#: the output formats (linecaster's names) a GPU encoder writes
GPU_ENCODE_FORMATS = frozenset({"jpg", "jp2"})
#: how to choose: ``auto`` (the GPU where it can, else the CPU), ``gpu`` (the GPU where it can; an error where none
#: is), ``cpu``
ACCEL = ("auto", "gpu", "cpu")


@cache
def cuda_devices() -> int:
    """How many CUDA devices the driver sees (``CUDA_VISIBLE_DEVICES`` applies); 0 without an NVIDIA driver."""
    for name in ("libcuda.so.1", "libcuda.so", "nvcuda.dll"):
        try:
            lib = ctypes.CDLL(name)
        except OSError:
            continue
        count = ctypes.c_int(0)
        if lib.cuInit(0) != 0 or lib.cuDeviceGetCount(ctypes.byref(count)) != 0:
            return 0
        return count.value
    return 0


@cache
def nvimgcodec():
    """The ``nvidia.nvimgcodec`` module, or None when it is not installed (or does not load)."""
    os.environ.setdefault(VERBOSITY_ENV, QUIET)           # read when the module loads
    try:
        import nvidia.nvimgcodec as nvc
    except Exception:  # noqa: BLE001 - not installed, or its libraries do not load: the CPU then
        return None
    return nvc


def gpu_available() -> bool:
    """Whether images can be decoded and encoded on a GPU here: a CUDA device and nvImageCodec."""
    return cuda_devices() > 0 and nvimgcodec() is not None


def use_gpu(accel: str, supported: bool) -> bool:
    """Whether to use the GPU for one image: ``accel`` (``ACCEL``) and whether the GPU supports its format.
    ``gpu`` without a usable GPU is an error (``RuntimeError``), not a quiet fallback.

    Args:
        accel: ``auto``, ``gpu`` or ``cpu``.
        supported: whether a GPU implementation handles this format (and mode).
    """
    if accel not in ACCEL:
        raise ValueError(f"accel {accel!r}: one of {', '.join(ACCEL)}")
    if accel == "cpu":
        return False
    if accel == "gpu" and not gpu_available():
        raise RuntimeError("accel gpu: no CUDA device or no nvImageCodec here (pip install 'linecaster[nvimgcodec]')")
    return supported and gpu_available()


def device_for(index: int) -> int:
    """The device a process with worker index ``index`` uses: one GPU per worker, round robin."""
    return index % max(1, cuda_devices())


class Batcher:
    """Calls ``fn(items) -> results`` with what several threads submit at once: the first caller waits ``wait``
    seconds (or until ``max_batch`` are there), then runs the batch for everyone. ``submit`` blocks until its own
    result is there and returns it (or raises what ``fn`` raised). One batch runs at a time (``run_lock``, which
    batchers that share one codec share): nvImageCodec's decoder and encoder are not safe to call from two threads at
    once; the next batch gathers meanwhile."""

    def __init__(self, fn: Callable[[list], list], max_batch: int = 64, wait: float = 0.003,
                 run_lock: threading.Lock | None = None):
        self.fn, self.max_batch, self.wait = fn, max_batch, wait
        self.run_lock = run_lock or threading.Lock()
        self._lock = threading.Condition()
        self._pending: list[list] = []                       # [item, result, done event, error]
        self._leader = False

    def submit(self, item):
        entry = [item, None, threading.Event(), None]
        with self._lock:
            self._pending.append(entry)
            lead = not self._leader
            if lead:
                self._leader = True
            else:
                self._lock.notify_all()
        if lead:
            self._lead()
        entry[2].wait()
        if entry[3] is not None:
            raise entry[3]
        return entry[1]

    def _lead(self) -> None:
        deadline = time.monotonic() + self.wait
        with self._lock:
            while len(self._pending) < self.max_batch and (left := deadline - time.monotonic()) > 0:
                self._lock.wait(left)
            batch, self._pending = self._pending[:self.max_batch], self._pending[self.max_batch:]
            more = bool(self._pending)
            self._leader = False
        try:
            with self.run_lock:
                results = self.fn([e[0] for e in batch])
            for e, r in zip(batch, results, strict=True):
                e[1] = r
        except BaseException as err:  # noqa: BLE001 - every caller of the batch gets it
            for e in batch:
                e[3] = err
        for e in batch:
            e[2].set()
        if more:                                             # the rest waited for this batch: one of them leads
            with self._lock:
                if self._pending and not self._leader:
                    self._leader = True
                    threading.Thread(target=self._lead, daemon=True).start()


class GpuCodec:
    """One CUDA device's nvImageCodec decoder and encoder (GPU implementations only), shared by a process's threads;
    see the module docstring. ``decode`` and ``encode`` take one image and batch with concurrent calls.

    Args:
        device: the CUDA device.
    """

    def __init__(self, device: int = 0):
        nvc = nvimgcodec()
        if nvc is None:
            raise RuntimeError("nvImageCodec is not installed (pip install 'linecaster[nvimgcodec]')")
        self.nvc, self.device = nvc, device
        decoders, encoders = available(nvc.get_decoder_ids(), GPU_DECODERS), available(nvc.get_encoder_ids(), GPU_ENCODERS)
        if not decoders:
            raise RuntimeError("nvImageCodec has none of its GPU decoders here (nvJPEG, nvJPEG2000, nvTIFF did not "
                               "load)")
        self.decoder = nvc.Decoder(device_id=device, decoder_ids=decoders)
        self.encoder = nvc.Encoder(device_id=device, encoder_ids=encoders) if encoders else None
        self._decode = Batcher(self._decode_batch)
        self._encode: dict[tuple, Batcher] = {}
        self._encode_lock = threading.Lock()
        self._encoding = threading.Lock()                    # one encode call at a time, whatever its settings

    @property
    def version(self) -> str:
        """e.g. ``"nvImageCodec 0.10.0"``."""
        return f"nvImageCodec {getattr(self.nvc, '__version__', '?')}"

    def decode(self, data: bytes, gray: bool):
        """The image's pixels as an 8-bit array (height x width, ``gray``; height x width x 3, RGB), not oriented by
        EXIF and with no colour management (the caller applies the ICC profile, as on the CPU); None when no GPU
        decoder takes it.

        Args:
            data: the image file's bytes.
            gray: decode to one channel (a grayscale source) instead of RGB.
        """
        return self._decode.submit((data, gray))

    def _decode_batch(self, items: list[tuple[bytes, bool]]) -> list:
        import numpy as np

        nvc = self.nvc
        out: list = [None] * len(items)
        for gray in (False, True):                           # one call per output layout
            idx = [i for i, (_, g) in enumerate(items) if g == gray]
            if not idx:
                continue
            params = nvc.DecodeParams(apply_exif_orientation=False, allow_any_depth=False,
                                      color_spec=nvc.ColorSpec.GRAY if gray else nvc.ColorSpec.SRGB,
                                      sample_format=nvc.SampleFormat.I_Y if gray else nvc.SampleFormat.I_RGB)
            images = self.decoder.decode([nvc.CodeStream(items[i][0]) for i in idx], params=params)
            for i, im in zip(idx, images, strict=True):
                if im is not None:
                    a = np.asarray(im.cpu())
                    out[i] = a[..., 0] if gray and a.ndim == 3 else a
        return out

    def encode(self, pixels, fmt: str, params: dict[str, Any]) -> bytes | None:
        """The image (8-bit RGB array, height x width x 3) encoded as ``fmt`` (``jpg``: ``quality``; ``jp2``:
        ``lossless`` or ``psnr``); None when no GPU encoder takes it.

        Args:
            pixels: the image's 8-bit RGB pixels.
            fmt: ``jpg`` or ``jp2``.
            params: the format's settings.
        """
        if self.encoder is None:
            return None
        key = (fmt, tuple(sorted(params.items())))
        with self._encode_lock:
            batcher = self._encode.get(key)
            if batcher is None:
                batcher = self._encode[key] = Batcher(lambda items, k=key: self._encode_batch(items, *k),
                                                      run_lock=self._encoding)
        return batcher.submit(pixels)

    def _encode_batch(self, items: Sequence, fmt: str, params: tuple) -> list:
        nvc, p = self.nvc, dict(params)
        if fmt == "jpg":
            ep = nvc.EncodeParams(quality_type=nvc.QualityType.QUALITY, quality_value=float(p["quality"]),
                                  chroma_subsampling=nvc.ChromaSubsampling.CSS_420,
                                  jpeg_encode_params=nvc.JpegEncodeParams(optimized_huffman=True))
            codec = "jpeg"
        else:
            lossless = p.get("lossless", True)
            ep = nvc.EncodeParams(quality_type=nvc.QualityType.LOSSLESS if lossless else nvc.QualityType.PSNR,
                                  quality_value=0.0 if lossless else float(p["psnr"]),
                                  jpeg2k_encode_params=nvc.Jpeg2kEncodeParams(
                                      bitstream_type=nvc.Jpeg2kBitstreamType.JP2, mct_mode=1))
            codec = "jpeg2k"
        images = [nvc.as_image(a) for a in items]
        encoded = self.encoder.encode(images, codec, params=ep)
        return [bytes(e) if e is not None else None for e in encoded]


def available(loaded: Sequence[str], wanted: Sequence[str]) -> list[str]:
    """The ``wanted`` GPU implementations nvImageCodec has loaded (``get_decoder_ids()``/``get_encoder_ids()``); the
    missing ones are said once (a library that did not load: its formats go to the CPU)."""
    have = [w for w in wanted if w in set(loaded)]
    missing = [w for w in wanted if w not in set(loaded)]
    if missing and tuple(missing) not in _SAID:
        _SAID.add(tuple(missing))
        logger.warning("nvImageCodec: {missing} not available here; what they would do runs on the CPU",
                       missing=", ".join(missing))
    return have


_SAID: set[tuple[str, ...]] = set()
_CODECS: dict[int, GpuCodec] = {}
_CODECS_LOCK = threading.Lock()


def gpu_codec(device: int) -> GpuCodec:
    """This process's ``GpuCodec`` for ``device`` (made at the first call)."""
    with _CODECS_LOCK:
        if device not in _CODECS:
            _CODECS[device] = GpuCodec(device)
        return _CODECS[device]
