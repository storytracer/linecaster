"""Page images as engines receive them (``linecaster.images.pixels``): plain RGB, decoded once, on a GPU where it can."""
from __future__ import annotations

import io
import threading

import numpy as np
import pytest
from PIL import Image

from linecaster.images import accel, pixels


def _noise(mode: str = "RGB", size=(97, 61), seed=0) -> Image.Image:
    a = np.random.default_rng(seed).integers(0, 256, (size[1], size[0], 3), dtype=np.uint8)
    return Image.fromarray(a).convert(mode)


def _encode(im: Image.Image, fmt: str, **kw) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format=fmt, **kw)
    return buf.getvalue()


def _pillow(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as im:
        return np.asarray(im.convert("RGB"))


class FakeGpu:
    """A GPU codec that decodes with Pillow in the source's layout (gray or RGB), or refuses or fails as told."""

    version = "FakeCodec 1"

    def __init__(self, answer: str = "decode"):
        self.answer, self.decoded = answer, []

    def decode(self, data: bytes, gray: bool):
        self.decoded.append(gray)
        if self.answer == "refuse":
            return None
        if self.answer == "fail":
            raise MemoryError("out of device memory")
        with Image.open(io.BytesIO(data)) as im:
            return np.asarray(im.convert("L" if gray else "RGB"))


@pytest.fixture(autouse=True)
def decoding():
    """Each test starts with no kept pages (they are kept by content, and the tests' images repeat) and leaves the
    process's choice as it found it."""
    before = pixels.decoding()
    pixels.clear()
    yield
    pixels.clear()
    pixels.set_decoding(*before)


@pytest.fixture
def fake_gpu(monkeypatch):
    gpu = FakeGpu()
    monkeypatch.setattr(accel, "gpu_available", lambda: True)
    monkeypatch.setattr(accel, "gpu_codec", lambda device: gpu)
    return gpu


def test_pillow_decodes_plain_rgb_once_per_file():
    """The pixels are Pillow's ``convert("RGB")``, read-only; a file is decoded once, whether the same bytes object
    comes again or a copy of it (a server's requests); another file, or another choice of decoding, is decoded."""
    data = _encode(_noise("P"), "PNG")
    before = pixels.decodes()
    px = pixels.decode_pixels(data, "cpu")
    assert np.array_equal(px.rgb, _pillow(data)) and not px.rgb.flags.writeable
    assert px.decoder.startswith("Pillow ") and px.fallback is None and not px.gpu
    assert pixels.decode_pixels(data, "cpu") is px and pixels.decodes() - before == 1
    assert pixels.last_decode() == (px, False)
    assert pixels.decode_pixels(bytes(bytearray(data)), "cpu") is px and pixels.decodes() - before == 1
    pixels.decode_pixels(_encode(_noise("P", seed=1), "PNG"), "cpu")
    assert pixels.decodes() - before == 2
    assert np.array_equal(pixels.rgb_image(data), _pillow(data))


def test_the_kept_pages_are_bounded_by_count_and_by_size():
    files = [_encode(_noise(size=(50, 40), seed=i), "PNG") for i in range(6)]
    try:
        pixels.keep(pages=3)
        for f in files:
            pixels.decode_pixels(f, "cpu")
        before = pixels.decodes()
        pixels.decode_pixels(files[-1], "cpu")                 # kept
        pixels.decode_pixels(files[0], "cpu")                  # dropped: the oldest of six past three
        assert pixels.decodes() - before == 1
        pixels.clear()
        pixels.keep(pages=100, nbytes=2 * 50 * 40 * 3)         # room for two such pages
        before = pixels.decodes()
        for f in files[:3]:
            pixels.decode_pixels(f, "cpu")
        pixels.decode_pixels(files[2], "cpu")
        pixels.decode_pixels(files[1], "cpu")
        assert pixels.decodes() - before == 3
        pixels.decode_pixels(files[0], "cpu")
        assert pixels.decodes() - before == 4
    finally:
        pixels.keep()


def test_the_last_decode_is_the_calling_threads():
    data = _encode(_noise(), "PNG")
    pixels.forget_last()
    seen = []
    t = threading.Thread(target=lambda: seen.append((pixels.decode_pixels(data, "cpu"), pixels.last_decode())))
    t.start()
    t.join()
    assert pixels.last_decode() is None and seen[0][1][0] is seen[0][0]


def test_a_gpu_decodes_8_bit_gray_and_rgb_jpeg_jp2_tiff_to_the_same_layout(fake_gpu):
    """Gray comes back repeated into three channels, as Pillow's ``convert("RGB")`` makes it; palette images, PNG and
    WebP stay with Pillow."""
    for data, gray in [(_encode(_noise(), "JPEG"), False), (_encode(_noise("L"), "JPEG2000"), True),
                       (_encode(_noise("L"), "TIFF"), True)]:
        px = pixels.decode_pixels(data, "auto")
        assert px.gpu and px.decoder == "FakeCodec 1 (GPU 0)" and np.array_equal(px.rgb, _pillow(data))
        assert px.rgb.shape[2] == 3 and not px.rgb.flags.writeable
        assert fake_gpu.decoded[-1] is gray
    count = len(fake_gpu.decoded)
    for data in (_encode(_noise("P"), "TIFF"), _encode(_noise(), "PNG"), _encode(_noise(), "WEBP", lossless=True)):
        assert not pixels.decode_pixels(data, "auto").gpu
    assert pixels.decode_pixels(_encode(_noise(), "JPEG"), "cpu").decoder.startswith("Pillow ")
    assert len(fake_gpu.decoded) == count


def test_the_process_choice_and_device_apply_where_a_call_names_none(fake_gpu):
    pixels.set_decoding("cpu")
    assert not pixels.decode_pixels(_encode(_noise(), "JPEG")).gpu
    pixels.set_decoding("auto", 3)
    assert pixels.decode_pixels(_encode(_noise(), "JPEG")).decoder == "FakeCodec 1 (GPU 3)"
    with pytest.raises(ValueError, match="one of auto, gpu, cpu"):
        pixels.set_decoding("fast")


@pytest.mark.parametrize("answer, fallback", [("refuse", "refused"), ("fail", "error: MemoryError: out of device memory")])
def test_what_a_gpu_does_not_decode_pillow_does(fake_gpu, answer, fallback):
    fake_gpu.answer = answer
    data = _encode(_noise(), "JPEG")
    px = pixels.decode_pixels(data, "auto")
    assert px.fallback == fallback and px.decoder.startswith("Pillow ") and np.array_equal(px.rgb, _pillow(data))
    with pytest.raises((RuntimeError, MemoryError)):
        pixels.decode_pixels(bytes(bytearray(data)), "gpu")


def test_without_a_gpu_auto_is_pillow_and_gpu_an_error(monkeypatch):
    monkeypatch.setattr(accel, "gpu_available", lambda: False)
    data = _encode(_noise(), "JPEG")
    assert pixels.decode_pixels(data, "auto").decoder.startswith("Pillow ")
    with pytest.raises(RuntimeError, match="no CUDA device or no nvImageCodec"):
        pixels.decode_pixels(bytes(bytearray(data)), "gpu")


needs_gpu = pytest.mark.skipif(not accel.gpu_available(), reason="no CUDA device or no nvImageCodec here")


@needs_gpu
def test_on_a_real_gpu_plain_pixels_are_within_a_few_steps_of_pillows():
    """nvJPEG2000 decodes a lossless JPEG 2000 exactly, nvJPEG within three steps of 255 of libjpeg-turbo."""
    page = _noise(size=(640, 480))
    for data, most in ((_encode(page, "JPEG", quality=90), 3), (_encode(page, "JPEG2000"), 0),
                       (_encode(page.convert("L"), "JPEG"), 3), (_encode(page.convert("L"), "JPEG2000"), 0)):
        px = pixels.decode_pixels(data, "gpu")
        assert px.gpu and px.rgb.shape == (480, 640, 3)
        assert int(np.abs(px.rgb.astype(int) - _pillow(data).astype(int)).max()) <= most


def test_a_process_forked_after_cuda_started_decodes_with_pillow(monkeypatch):
    """CUDA does not work across fork: a child of a process that called cuInit sees no device, so ``auto`` decodes
    with Pillow there (and ``gpu`` is an error) instead of hanging on its parent's GPU."""
    import multiprocessing

    monkeypatch.setattr(accel, "_CUDA_STARTED", [True])
    data = _encode(_noise(), "JPEG")
    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(1) as pool:
        devices, decoder = pool.apply(_in_child, (data,))
    assert devices == 0 and decoder.startswith("Pillow ")


def _in_child(data: bytes):
    return accel.cuda_devices(), pixels.decode_pixels(data, "auto").decoder
