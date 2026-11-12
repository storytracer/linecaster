"""Image conversion (``linecaster.images.transcode``, ``linecaster.images.accel``, ``ImageConverter`` with an
``image.convert.v1`` preset, ``pipelines/convert.py``'s shape): every output format at full resolution with the
working image's colour handling; the GPU chosen where the machine has one (here: a fake GPU codec that decodes with
Pillow, so the GPU branch's plumbing is checked on any machine); the stages, resume, temporary names, rejects and the
input's order."""
from __future__ import annotations

import io
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from datatrove.data import Document
from PIL import Image, ImageCms

from linecaster.blocks.base.page import page_of, set_page
from linecaster.blocks.conversion.images import ImageConverter
from linecaster.blocks.readers.images import ImageFolderReader
from linecaster.data.page import Page, PageImage
from linecaster.images import accel, transcode
from linecaster.images.convert import to_working_webp


def _noise(mode: str = "RGB", size=(97, 61), seed=0) -> Image.Image:
    rng = np.random.default_rng(seed)
    bands = {"RGB": 3, "RGBA": 4, "LA": 2}.get(mode, 1)
    shape = (size[1], size[0], bands) if bands > 1 else (size[1], size[0])
    return Image.fromarray(rng.integers(0, 256, shape, dtype=np.uint8), mode)


def _encode(im: Image.Image, fmt: str, **kw) -> bytes:
    buf = io.BytesIO()
    im.save(buf, fmt, **kw)
    return buf.getvalue()


def _decode(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as im:
        return np.asarray(im.convert("RGB"))


ADOBE_LIKE = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()   # any profile that is not sRGB


SOURCES = {
    "jpeg rgb": lambda: _encode(_noise(), "JPEG", quality=90),
    "jpeg gray": lambda: _encode(_noise("L"), "JPEG"),
    "jp2 rgb": lambda: _encode(_noise(), "JPEG2000"),
    "png rgba": lambda: _encode(_noise("RGBA"), "PNG"),
    "tiff 16-bit": lambda: _encode(Image.fromarray((np.arange(61 * 97).reshape(61, 97) * 10).astype(np.uint16)),
                                   "TIFF"),
    "png with icc": lambda: _encode(_noise(), "PNG",
                                    icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()),
}


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("fmt, settings", [("webp", {"quality": 80}), ("jpg", {"quality": 90}), ("png", {}),
                                           ("jp2", {"lossless": True}), ("jp2", {"psnr": 40.0})])
def test_every_source_converts_to_every_format_with_the_working_images_pixels(source, fmt, settings):
    """The decoded pixels are the working image's (same colour handling); the file opens at full resolution; the
    lossless outputs decode to exactly those pixels; the record names the decoder and the encoder."""
    data = SOURCES[source]()
    out, rec = transcode.convert(data, fmt, accel="cpu", **settings)
    assert rec["pixels_sha256"] == to_working_webp(data)[1]["pixels_sha256"]
    with Image.open(io.BytesIO(out)) as im:
        assert im.size == (97, 61) and im.format == transcode.FORMATS[fmt][0]
    assert rec["format"] == transcode.FORMATS[fmt][1] and rec["bytes"] == len(out)
    assert rec["decoder"].startswith("Pillow ") and rec["encoder"].startswith("Pillow ")
    if fmt == "png" or settings.get("lossless"):
        assert transcode.hashlib.sha256(_decode(out).tobytes()).hexdigest() == rec["pixels_sha256"]


def test_webp_lossless_and_jp2_settings_are_errors_where_incomplete():
    rgb = _noise()
    out, _ = transcode.encode(rgb, "webp", lossless=True)
    assert np.array_equal(_decode(out), np.asarray(rgb))
    with pytest.raises(ValueError, match="jp2: lossless, or a psnr"):
        transcode.encode(rgb, "jp2")
    with pytest.raises(ValueError, match="format 'gif'"):
        transcode.encode(rgb, "gif")


# ------------------------------------------------------------------ the GPU, where the machine has one

def test_without_a_gpu_auto_and_cpu_use_the_cpu_and_gpu_is_an_error(monkeypatch):
    monkeypatch.setattr(accel, "gpu_available", lambda: False)
    assert not accel.use_gpu("auto", True) and not accel.use_gpu("cpu", True)
    with pytest.raises(RuntimeError, match="no CUDA device or no nvImageCodec"):
        accel.use_gpu("gpu", True)
    with pytest.raises(ValueError, match="one of auto, gpu, cpu"):
        accel.use_gpu("fast", True)
    monkeypatch.setattr(accel, "gpu_available", lambda: True)
    assert accel.use_gpu("auto", True) and not accel.use_gpu("auto", False) and not accel.use_gpu("cpu", True)


class FakeGpu:
    """A GPU codec that decodes with Pillow (in the source's mode, no colour management) and encodes JPEG with Pillow,
    counting its calls."""

    version = "FakeCodec 1"

    def __init__(self):
        self.decoded, self.encoded = [], []

    def decode(self, data: bytes, gray: bool):
        self.decoded.append(gray)
        with Image.open(io.BytesIO(data)) as im:
            return np.asarray(im.convert("L" if gray else "RGB"))

    def encode(self, pixels, fmt: str, params: dict):
        self.encoded.append((fmt, params))
        return _encode(Image.fromarray(pixels), "JPEG", quality=params["quality"]) if fmt == "jpg" else None


@pytest.fixture
def fake_gpu(monkeypatch):
    gpu = FakeGpu()
    monkeypatch.setattr(accel, "gpu_available", lambda: True)
    monkeypatch.setattr(accel, "gpu_codec", lambda device: gpu)
    return gpu


def test_a_gpu_decode_goes_through_the_same_colour_handling(fake_gpu):
    """JPEG, JPEG 2000 and TIFF in 8-bit gray or RGB are decoded on the GPU, in the source's mode and with its ICC
    profile handed on, so the pixels are the CPU path's; other modes and formats stay on the CPU."""
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    for data, gray in [(_encode(_noise(), "JPEG", icc_profile=srgb), False), (_encode(_noise("L"), "JPEG2000"), True),
                       (_encode(_noise(), "TIFF"), False)]:
        gpu, cpu = transcode.decode(data, "auto"), transcode.decode(data, "cpu")
        assert gpu.decoder == "FakeCodec 1 (GPU 0)" and fake_gpu.decoded[-1] == gray
        assert np.array_equal(np.asarray(gpu.rgb), np.asarray(cpu.rgb)) and gpu.notes == cpu.notes
    n = len(fake_gpu.decoded)
    for data in (_encode(_noise("RGBA"), "PNG"), _encode(_noise(), "WEBP")):
        assert transcode.decode(data, "auto").decoder.startswith("Pillow ")
    assert len(fake_gpu.decoded) == n
    assert transcode.compare_decoders(_encode(_noise(), "JPEG"))["max_abs"] == 0


def test_jpeg_is_encoded_on_the_gpu_png_and_webp_never(fake_gpu):
    rgb = _noise()
    out, encoder = transcode.encode(rgb, "jpg", quality=90)
    assert encoder == "FakeCodec 1 (GPU 0)" and fake_gpu.encoded == [("jpg", {"quality": 90})]
    for fmt in ("webp", "png"):
        assert transcode.encode(rgb, fmt)[1].startswith("Pillow ")
    assert transcode.encode(rgb, "jp2", lossless=True)[1].startswith("Pillow ")      # the fake takes no JPEG 2000
    with pytest.raises(RuntimeError, match="no GPU encoder took this image as jp2"):
        transcode.encode(rgb, "jp2", lossless=True, accel="gpu")
    assert transcode.encode(rgb, "jpg", accel="cpu")[1].startswith("Pillow ")


def test_the_batcher_hands_each_caller_its_own_result_from_shared_batches():
    sizes = []

    def double(items):
        sizes.append(len(items))
        time.sleep(0.01)
        return [2 * x for x in items]

    b = accel.Batcher(double, max_batch=8, wait=0.02)
    got = {}
    threads = [threading.Thread(target=lambda i=i: got.__setitem__(i, b.submit(i))) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert got == {i: 2 * i for i in range(20)} and max(sizes) <= 8 and len(sizes) < 20

    def boom(items):
        raise OSError("device lost")

    with pytest.raises(OSError, match="device lost"):
        accel.Batcher(boom).submit(1)


# ------------------------------------------------------------------ the block

def _doc(page: Page) -> Document:
    d = Document(text="", id=page.page_id, metadata={}, media=[])
    set_page(d, page)
    return d


def _pages(tmp_path: Path, n: int = 6) -> list[Page]:
    (tmp_path / "scans").mkdir()
    pages = []
    for i in range(n):
        path = tmp_path / "scans" / f"p{i}.jp2"
        path.write_bytes(_encode(_noise(seed=i), "JPEG2000"))
        pages.append(Page(page_id=f"b_{i}", item_id="b", image=PageImage(uri=str(path))))
    (tmp_path / "scans" / "bad.jp2").write_bytes(b"not an image")
    pages.insert(3, Page(page_id="b_bad", item_id="b", image=PageImage(uri=str(tmp_path / "scans" / "bad.jp2"))))
    return pages


@pytest.mark.parametrize("window", [None, 2])
def test_the_converter_writes_every_page_in_the_inputs_order_and_goes_on_after_a_failure(tmp_path, window):
    pages = _pages(tmp_path)
    block = ImageConverter(str(tmp_path / "out"), "webp-lossy-q80", window=window, max_window=4)
    docs = list(block.run(iter(map(_doc, pages))))
    assert [d.id for d in docs] == [p.page_id for p in pages]
    bad = docs[3]
    assert bad.metadata["errors"][0]["field"] == "image" and "cannot convert" in bad.metadata["errors"][0]["error"]
    files = sorted(p.name for p in (tmp_path / "out" / "b").iterdir())
    assert files == [f"b_{i}.webp" for i in range(6)]                         # no .part left
    img = page_of(docs[0]).image
    assert img.format == "webp" and (img.width, img.height) == (97, 61) and img.uri.endswith("out/b/b_0.webp")
    assert img.decoder.startswith("Pillow ") and img.extra["encoder"].startswith("Pillow ")
    assert img.extra["bytes"] == (tmp_path / "out" / "b" / "b_0.webp").stat().st_size
    assert img.extra["original"]["format"] == "jpeg2000" and img.extra["step"]["preset"] == "webp-lossy-q80@1"
    assert docs[0].media == []


def test_a_rerun_skips_the_files_there_already(tmp_path):
    pages = _pages(tmp_path)
    list(ImageConverter(str(tmp_path / "out"), "jpeg-q90").run(iter(map(_doc, pages))))
    first = tmp_path / "out" / "b" / "b_0.jpg"
    stamp = first.stat().st_mtime_ns
    again = list(ImageConverter(str(tmp_path / "out"), "jpeg-q90").run(iter(map(_doc, pages))))
    assert first.stat().st_mtime_ns == stamp
    img = page_of(again[0]).image
    assert img.extra["existing"] and (img.width, img.height) == (97, 61) and img.format == "jpg"
    redo = list(ImageConverter(str(tmp_path / "out"), "jpeg-q90", skip_existing=False).run(iter(map(_doc, pages))))
    assert "existing" not in page_of(redo[0]).image.extra


def test_the_working_image_runs_through_the_same_stages_unchanged(tmp_path):
    pages = _pages(tmp_path, 2)
    docs = list(ImageConverter(str(tmp_path / "out"), "working-image@1").run(iter(map(_doc, pages))))
    img = page_of(docs[0]).image
    data = (tmp_path / "scans" / "p0.jp2").read_bytes()
    want, info = to_working_webp(data)
    assert (tmp_path / "out" / "b" / "b_0.webp").read_bytes() == want and img.sha256 == info["sha256"]
    assert img.extra["webp_settings"] == info["webp_settings"] and "encoder" not in img.extra


def test_an_image_folder_read_without_its_files_gives_addresses(tmp_path):
    (tmp_path / "it").mkdir()
    (tmp_path / "it" / "a_0001.jp2").write_bytes(_encode(_noise(), "JPEG2000"))
    reader = ImageFolderReader(str(tmp_path), item_from_parent=True, read_images=False)
    (doc,) = list(reader.run())
    page = page_of(doc)
    assert doc.media == [] and page.item_id == "it" and page.image.format == "jpeg2000"
    assert page.image.uri.endswith("it/a_0001.jp2") and page.image.width is None
    assert reader.contract().adds and "image" not in str(reader.contract().adds)


def test_the_convert_pipeline_takes_one_worker_per_gpu(monkeypatch, tmp_path):
    from linecaster.pipelines import convert
    from linecaster.runtime import run

    monkeypatch.setattr(accel, "cuda_devices", lambda: 4)
    a = run.parse([str(tmp_path), str(tmp_path / "out"), "--preset", "webp-lossy-q80", "--set", "image.quality=70"],
                  convert.__doc__, convert.options, convert.PIPELINE, convert.SLOTS)
    steps, extra = convert.pipeline(a, "convert.py")
    assert a.workers == 4 and extra == {"engines": False}
    assert steps[0].read_images is False and steps[1].backend.kwargs["quality"] == 70
