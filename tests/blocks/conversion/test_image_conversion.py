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

    running, most = [0], [0]

    def one_at_a_time(items):
        running[0] += 1
        most[0] = max(most[0], running[0])
        time.sleep(0.01)
        running[0] -= 1
        return items

    b = accel.Batcher(one_at_a_time, max_batch=2, wait=0)
    threads = [threading.Thread(target=b.submit, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert most[0] == 1                                       # nvImageCodec is not safe from two threads at once

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
    block = ImageConverter(str(tmp_path / "out"), "webp-lossy-q80", options={"accel": "cpu"}, window=window,
                           max_window=4)
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
    assert img.extra["original"]["format"] == "jpeg2000" and img.extra["step"]["preset"] == "webp-lossy-q80@2"
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
    monkeypatch.setattr(accel, "gpu_available", lambda: True)
    a = run.parse([str(tmp_path), str(tmp_path / "out"), "--preset", "webp-lossy-q80", "--set", "image.quality=70"],
                  convert.__doc__, convert.options, convert.PIPELINE, convert.SLOTS)
    steps, extra = convert.pipeline(a, "convert.py")
    assert a.workers == 4 and extra == {"engines": False}
    assert steps[0].read_images is False and steps[1].backend.kwargs["quality"] == 70


# ------------------------------------------------------------------ a real GPU, where the machine has one

needs_gpu = pytest.mark.skipif(not accel.gpu_available(), reason="no CUDA device or no nvImageCodec here")


@needs_gpu
def test_on_a_real_gpu_decoding_matches_pillow_within_one_step_and_encoding_reads_back():
    """After the same colour handling, nvJPEG2000 decodes within one step of 255 of OpenJPEG and nvJPEG within three of
    libjpeg-turbo (its own inverse DCT and colour conversion; its fancy upsampling is on); JPEG and JPEG 2000 encoded on
    the GPU read back at full size, lossless JPEG 2000 exactly."""
    page = _noise(size=(640, 480))
    for data, most in ((_encode(page, "JPEG", quality=90), 3), (_encode(page, "JPEG2000"), 0),
                       (_encode(page.convert("L"), "JPEG"), 3),
                       (_encode(page, "JPEG2000", irreversible=True, quality_mode="dB", quality_layers=[38]), 1)):
        r = transcode.compare_decoders(data)
        assert r["gpu"] and r["max_abs"] <= most, r
    rgb = transcode.decode(_encode(page, "PNG"), "cpu").rgb
    out, encoder = transcode.encode(rgb, "jpg", quality=90, accel="gpu")
    assert "GPU" in encoder and Image.open(io.BytesIO(out)).size == (640, 480)
    out, encoder = transcode.encode(rgb, "jp2", lossless=True, accel="gpu")
    assert "GPU" in encoder and np.array_equal(_decode(out), np.asarray(rgb))


def test_files_for_a_hub_bucket_go_up_in_batches(tmp_path, monkeypatch):
    """Into a Hugging Face bucket the converter uploads what is written at about the same time in one call
    (``HfApi.batch_bucket_files``), at the output folder's path in the bucket."""
    import huggingface_hub

    from linecaster.blocks.conversion import images as block

    calls = []

    class FakeApi:
        def batch_bucket_files(self, bucket_id, add):
            calls.append((bucket_id, [dest for _, dest in add]))

    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)
    monkeypatch.setattr(block, "_hub_bucket", lambda out: ("ns/runs", "run-1/images"))
    pages = _pages(tmp_path)
    docs = list(ImageConverter(str(tmp_path / "out"), "webp-lossy-q80", options={"accel": "cpu"}).run(
        iter(map(_doc, pages))))
    assert sum(not d.metadata.get("errors") for d in docs) == 6
    assert {b for b, _ in calls} == {"ns/runs"} and len(calls) < 6
    assert sorted(p for _, batch in calls for p in batch) == [f"run-1/images/b/b_{i}.webp" for i in range(6)]


def test_on_ray_the_convert_tasks_reserve_a_gpu_and_its_share_of_the_cpus(monkeypatch, tmp_path):
    """Ray hides the GPUs from a task that reserved none: where GPUs decode, each task reserves one
    (``RayGPUExecutor``) and the CPUs divided by the GPUs; without GPUs, or with ``accel=cpu``, CPU tasks, one worker
    per CPU (Pillow's JPEG 2000 decoder holds the GIL)."""
    from linecaster.pipelines import convert
    from linecaster.runtime import cpus, run

    monkeypatch.setattr(cpus, "available_cpus", lambda: 124)
    argv = [str(tmp_path), str(tmp_path / "out"), "--preset", "webp-lossy-q80", "--on", "ray"]
    for gpus, extra, executor, workers, per_task in ((8, [], "RayGPUExecutor", 8, 15),
                                                     (0, [], "RayExecutor", 124, 1),
                                                     (8, ["--set", "image.accel=cpu"], "RayExecutor", 124, 1)):
        monkeypatch.setattr(accel, "cuda_devices", lambda g=gpus: g)
        monkeypatch.setattr(accel, "gpu_available", lambda g=gpus: g > 0)
        a = run.parse(argv + extra, convert.__doc__, convert.options, convert.PIPELINE, convert.SLOTS)
        a.has_engines = bool(convert.models(a))                    # as run.main sets it
        convert.pipeline(a, "convert.py")
        assert (run.executor_name(a), a.workers, a.cpus_per_task) == (executor, workers, per_task)
    a = run.parse([*argv, "--cpus-per-task", "4"], convert.__doc__, convert.options, convert.PIPELINE, convert.SLOTS)
    monkeypatch.setattr(accel, "cuda_devices", lambda: 8)
    monkeypatch.setattr(accel, "gpu_available", lambda: True)
    convert.pipeline(a, "convert.py")
    assert a.cpus_per_task == 4                                     # given: kept


class BrokenGpu(FakeGpu):
    """A GPU that refuses some files and fails on others, the way nvImageCodec does: a rejection is None, a failure
    of the GPU an exception."""

    def decode(self, data: bytes, gray: bool):
        if gray:
            return None                                       # e.g. a code stream nvJPEG2000 does not support
        raise RuntimeError("CUDA error: out of memory")

    def encode(self, pixels, fmt: str, params: dict):
        raise RuntimeError("CUDA error: device lost")


def test_whatever_keeps_the_gpu_from_an_image_the_cpu_does_and_says_why(monkeypatch, tmp_path):
    """A file the GPU rejects and a GPU that fails both fall back to Pillow, recorded as ``gpu_fallback``; the block
    counts them and logs the failures; ``accel=gpu`` makes both an error."""
    monkeypatch.setattr(accel, "gpu_available", lambda: True)
    monkeypatch.setattr(accel, "gpu_codec", lambda device: BrokenGpu())
    gray, rgb = _encode(_noise("L"), "JPEG2000"), _encode(_noise(), "JPEG2000")
    refused, failed = transcode.decode(gray, "auto"), transcode.decode(rgb, "auto")
    assert refused.decoder.startswith("Pillow ") and refused.notes["gpu_fallback"] == {"decode": "refused"}
    assert failed.notes["gpu_fallback"] == {"decode": "error: RuntimeError: CUDA error: out of memory"}
    assert np.array_equal(np.asarray(failed.rgb), np.asarray(transcode.decode(rgb, "cpu").rgb))
    out, rec = transcode.convert(rgb, "jpg", quality=90)
    assert rec["encoder"].startswith("Pillow ") and rec["gpu_fallback"]["encode"].startswith("error: RuntimeError")
    with pytest.raises(RuntimeError, match="out of memory"):
        transcode.decode(rgb, "gpu")
    with pytest.raises(RuntimeError, match="no GPU decoder took"):
        transcode.decode(gray, "gpu")

    lines = []
    sink = logger_add(lines)
    try:
        pages = _pages(tmp_path, 2)
        block = ImageConverter(str(tmp_path / "out"), "jpeg-q90")
        docs = list(block.run(iter(map(_doc, pages))))
    finally:
        sink()
    assert [d.id for d in docs if not d.metadata.get("errors")] == ["b_0", "b_1"]      # b_bad: not an image at all
    assert page_of(docs[0]).image.extra["gpu_fallback"]["decode"].startswith("error:")
    assert block.stats["gpu_decode_errors"].total == 2 and block.stats["gpu_encode_errors"].total == 2
    assert sum("the GPU could not decode it, the CPU did" in m for m in lines) == 2


def logger_add(lines: list):
    from loguru import logger

    sink = logger.add(lambda m: lines.append(m.record["message"]), level="WARNING")
    return lambda: logger.remove(sink)


def test_pillow_decodes_one_jpeg_2000_image_at_a_time_per_process(monkeypatch):
    """Pillow's JPEG 2000 decoder holds the GIL for the whole decode: the CPU path decodes one at a time per process,
    so concurrent pages wait with their bytes instead of allocating OpenJPEG's buffers; other formats are not held."""
    from PIL import Jpeg2KImagePlugin, JpegImagePlugin

    running, most = {"jp2": 0, "jpg": 0}, {"jp2": 0, "jpg": 0}
    lock = threading.Lock()

    def counting(kind, load):
        def wrapped(self):
            with lock:
                running[kind] += 1
                most[kind] = max(most[kind], running[kind])
            time.sleep(0.02)
            try:
                return load(self)
            finally:
                with lock:
                    running[kind] -= 1
        return wrapped

    monkeypatch.setattr(Jpeg2KImagePlugin.Jpeg2KImageFile, "load",
                        counting("jp2", Jpeg2KImagePlugin.Jpeg2KImageFile.load))
    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "load", counting("jpg", JpegImagePlugin.JpegImageFile.load))
    jp2, jpg = _encode(_noise(), "JPEG2000"), _encode(_noise(), "JPEG")
    threads = [threading.Thread(target=transcode.decode, args=(d, "cpu")) for d in [jp2] * 6 + [jpg] * 6]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert most["jp2"] == 1 and most["jpg"] > 1
