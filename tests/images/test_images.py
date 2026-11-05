"""Working-image conversion: lossless WebP, 8-bit sRGB, size limits checked before decoding."""
from __future__ import annotations

import hashlib
import io
import struct
import zlib

import numpy as np
import pytest
from PIL import Image, ImageCms, features

from linecaster.images import convert as images
from linecaster.images.convert import ImageTooLarge, check_size, read_header, to_working_webp


def _encode(im: Image.Image, fmt: str, **kw) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format=fmt, **kw)
    return buf.getvalue()


def _decode(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as im:
        return np.asarray(im.convert("RGB") if im.mode != "RGB" else im)


def _noise(mode: str, size=(97, 61), seed=0) -> Image.Image:
    rng = np.random.default_rng(seed)
    bands = len(mode) if mode in ("RGB", "RGBA", "LA") else 1
    shape = (size[1], size[0], bands) if bands > 1 else (size[1], size[0])
    return Image.fromarray(rng.integers(0, 256, shape, dtype=np.uint8), mode)


def _assert_lossless_webp(data: bytes) -> None:
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    assert data[12:16] == b"VP8L", "the output must be lossless WebP (VP8L)"


@pytest.mark.parametrize("fmt", ["PNG", "TIFF", "JPEG", "WEBP", "BMP"])
def test_rgb_round_trip_pixel_identity(fmt):
    src = _noise("RGB")
    data = _encode(src, fmt, **({"quality": 85} if fmt == "JPEG" else {}))
    webp, info = to_working_webp(data)
    _assert_lossless_webp(webp)
    decoded_source = _decode(data)                # what Pillow decodes from the source
    assert np.array_equal(_decode(webp), decoded_source)
    assert info["width"] == 97 and info["height"] == 61
    assert info["source_format"] == fmt.lower()
    assert info["pixels_sha256"] == hashlib.sha256(decoded_source.tobytes()).hexdigest()
    assert info["sha256"] == hashlib.sha256(webp).hexdigest()
    assert info["decoder"].startswith("Pillow ") and "libwebp" in info["decoder"]
    assert info["icc_applied"] is False and info["alpha_flattened"] is False


@pytest.mark.skipif(not features.check("jpg_2000"), reason="Pillow without OpenJPEG")
def test_jp2_round_trip_and_decoder_string():
    src = _noise("RGB", size=(64, 48))
    data = _encode(src, "JPEG2000", irreversible=False)       # reversible 5/3 wavelet: lossless
    webp, info = to_working_webp(data)
    assert np.array_equal(_decode(webp), np.asarray(src))
    assert info["source_format"] == "jpeg2000"
    assert "OpenJPEG" in info["decoder"]


def test_grayscale_becomes_rgb():
    src = _noise("L")
    webp, info = to_working_webp(_encode(src, "PNG"))
    out = _decode(webp)
    g = np.asarray(src)
    assert out.shape == (61, 97, 3)
    for c in range(3):
        assert np.array_equal(out[..., c], g)
    assert info["source_mode"] == "L"


def test_bilevel_and_palette():
    bw = _noise("L").point(lambda v: 255 if v > 127 else 0).convert("1")
    out = _decode(to_working_webp(_encode(bw, "TIFF", compression="group4"))[0])
    assert set(np.unique(out)) <= {0, 255}
    pal = _noise("RGB").convert("P", palette=Image.Palette.ADAPTIVE, colors=16)
    out = _decode(to_working_webp(_encode(pal, "PNG"))[0])
    assert np.array_equal(out, np.asarray(pal.convert("RGB")))


def test_alpha_is_flattened_on_white():
    a = np.zeros((10, 20, 4), dtype=np.uint8)
    a[..., :3] = (10, 20, 30)
    a[:, :10, 3] = 255          # left half opaque
    a[:, 10:, 3] = 0            # right half transparent
    webp, info = to_working_webp(_encode(Image.fromarray(a, "RGBA"), "PNG"))
    out = _decode(webp)
    assert (out[:, :10] == (10, 20, 30)).all()
    assert (out[:, 10:] == 255).all()
    assert info["alpha_flattened"] is True


def test_opaque_alpha_is_dropped_without_change():
    a = np.asarray(_noise("RGBA"))
    a = a.copy()
    a[..., 3] = 255
    webp, info = to_working_webp(_encode(Image.fromarray(a, "RGBA"), "PNG"))
    assert np.array_equal(_decode(webp), a[..., :3])
    assert info["alpha_flattened"] is False


def test_16bit_grayscale_png_scaled_to_8bit():
    rng = np.random.default_rng(1)
    a16 = rng.integers(0, 65536, (30, 40), dtype=np.uint16)
    a16[0, 0], a16[0, 1] = 0, 65535
    data = _encode(Image.fromarray(a16), "PNG")
    with Image.open(io.BytesIO(data)) as im:
        assert im.mode.startswith("I")              # Pillow reads it as 16-bit grayscale
    webp, info = to_working_webp(data)
    out = _decode(webp)
    want = ((a16.astype(np.int64) * 255 + 32767) // 65535).astype(np.uint8)
    assert np.array_equal(out[..., 0], want)
    assert out[0, 0, 0] == 0 and out[0, 1, 0] == 255


def test_icc_profile_is_applied():
    src = _noise("RGB")
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    data = _encode(src, "PNG", icc_profile=srgb)
    webp, info = to_working_webp(data)
    assert info["icc_applied"] is True
    diff = np.abs(_decode(webp).astype(int) - np.asarray(src).astype(int))
    assert diff.max() <= 2                          # sRGB -> sRGB is (nearly) the identity


def test_broken_icc_profile_falls_back():
    data = _encode(_noise("RGB"), "PNG", icc_profile=b"not a profile")
    webp, info = to_working_webp(data)
    assert info["icc_applied"] is False and "icc_error" in info
    assert np.array_equal(_decode(webp), np.asarray(_noise("RGB")))


# ---------------------------------------------------------------- size limits


def test_check_size_limits():
    limit = 2 * Image.MAX_IMAGE_PIXELS
    assert check_size(16383, 100) is None
    assert "width 16384" in check_size(16384, 100)
    assert "height 16384" in check_size(100, 16384)
    side = int(limit ** 0.5)
    assert check_size(side, side) is None if side <= 16383 else True
    w = 16383
    h = limit // w + 1
    if h <= 16383:
        assert "MAX_IMAGE_PIXELS" in check_size(w, h)
    assert check_size(10000, 10000) is None          # 1e8 <= 2 * 89,478,485


def test_check_size_reads_pillow_limit_at_call_time(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    assert check_size(40, 50) is None                # 2000 == 2 x 1000
    assert "MAX_IMAGE_PIXELS" in check_size(41, 50)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", None)
    assert check_size(16383, 16383) is None


def _png_with_forged_size(width: int, height: int) -> bytes:
    """A valid 1x1 PNG whose IHDR claims another size (CRC fixed): only the header is consistent."""
    data = bytearray(_encode(Image.new("RGB", (1, 1), (1, 2, 3)), "PNG"))
    assert data[12:16] == b"IHDR"
    data[16:24] = struct.pack(">II", width, height)
    data[29:33] = struct.pack(">I", zlib.crc32(bytes(data[12:29])) & 0xFFFFFFFF)
    return bytes(data)


def test_forged_width_rejected_before_decoding(monkeypatch):
    data = _png_with_forged_size(20000, 10)
    assert read_header(data) == ("PNG", 20000, 10)
    loads = []
    monkeypatch.setattr(Image.Image, "load", lambda self, *a, **k: loads.append(1))
    with pytest.raises(ImageTooLarge) as e:
        to_working_webp(data)
    assert "width 20000" in e.value.reason and e.value.width == 20000
    assert loads == []                                 # nothing was decoded


def test_forged_pixel_count_rejected(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 5000)
    with pytest.raises(ImageTooLarge) as e:            # 10100 > 2 x 5000
        to_working_webp(_png_with_forged_size(100, 101))
    assert "MAX_IMAGE_PIXELS = 10000" in e.value.reason
    monkeypatch.undo()
    with pytest.raises(ImageTooLarge) as e:            # under WebP's limit, over the pixel limit
        to_working_webp(_png_with_forged_size(16000, 16000))
    assert "MAX_IMAGE_PIXELS" in e.value.reason


def test_pillow_limit_is_never_changed():
    before = Image.MAX_IMAGE_PIXELS
    to_working_webp(_encode(_noise("RGB"), "PNG"))
    with pytest.raises(ImageTooLarge):
        to_working_webp(_png_with_forged_size(20000, 10))
    assert Image.MAX_IMAGE_PIXELS == before


def test_between_limit_and_twice_limit_is_accepted(monkeypatch):
    """Pillow warns above MAX_IMAGE_PIXELS; up to twice that the page is converted."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 97 * 61 // 2 + 1)
    webp, info = to_working_webp(_encode(_noise("RGB"), "PNG"))
    assert info["width"] == 97
    _ = images.max_pixels()


def test_effort_changes_bytes_not_pixels():
    data = _encode(_noise("RGB"), "PNG")
    fast, i0 = to_working_webp(data, effort=0)
    slow, i1 = to_working_webp(data, effort=100)
    _assert_lossless_webp(fast)
    assert np.array_equal(_decode(fast), _decode(slow))
    assert i0["pixels_sha256"] == i1["pixels_sha256"]
    assert i0["webp_settings"]["quality"] == 0
