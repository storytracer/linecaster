"""Image blocks: page images loaded again by their address (``ImageFetcher``), and image conversion
(``ImageConverter``): the working image (lossless WebP), or JPEG, JPEG 2000, PNG or WebP with GPU decoding and
encoding where the machine has it, in stages kept busy by saturate's adaptive windows."""
from __future__ import annotations

import asyncio
import hashlib
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from datatrove.data import Media, MediaType
from datatrove.io import DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep
from loguru import logger

from ...data.page import PageImage
from ...errors import PageError
from ...images.convert import ImageTooLarge
from ..base.contract import Contract, Contracted, parts
from ..base.page import error_entry, page_of, record_error, set_page
from ..base.rule import now, rule_backend, stamp


def _read(uri: str) -> bytes:
    import fsspec

    with fsspec.open(uri, "rb") as f:
        return f.read()


def read_uri(uri: str, page_id: str = "", metadata: dict | None = None) -> bytes:
    """The image bytes at ``uri`` (any fsspec path); a fragment names a PDF page or a Parquet row
    (``linecaster.blocks.readers.fragments.read_image``), and one that names neither is a ``PageError``."""
    from ..readers.fragments import read_image

    return read_image(uri, _read, page_id, metadata)


class ImageFetcher(Contracted, PipelineStep):
    """Loads each page's image again from its address, for the blocks that need pixels.

    It reads ``page.image.uri`` (any fsspec path) into ``doc.media``: it replaces ``image``. A URI with a fragment
    names a part of its file (``file.pdf#page=<n>``: that page rendered as ``PdfReader`` renders it,
    ``file.parquet#<page_id>``: that row's image); one that cannot be resolved is the page's error (field
    ``image``, stat ``image_errors``), and the page passes on without image bytes. ``PageRecordReader(
    fetch_images=False)`` followed by an ``ImageFetcher`` after filtering avoids fetching the images of pages that
    are dropped anyway. A page without an image address is counted (``no_image``) and passed on as it is.
    """

    type = "🔠 - LINECASTER"
    name = "🖼️ image fetcher"
    parts_read = ("metadata",)
    parts_replaced = ("image",)

    def run(self, data, rank: int = 0, world_size: int = 1):
        for doc in data:
            page = page_of(doc)
            if page.image is None or not page.image.uri:
                self.stat_update("no_image")
                yield doc
                continue
            try:
                with self.track_time():
                    raw = read_uri(page.image.uri, doc.id, page.metadata)
            except PageError as e:          # a fragment that names nothing it can fetch
                record_error(doc, error_entry(self, e, field="image", raw_value=page.image.uri))
                self.stat_update("image_errors")
                doc.media = [m for m in doc.media if m.type != MediaType.IMAGE]
                yield doc
                continue
            doc.media = [Media(id=doc.id, type=MediaType.IMAGE, url=page.image.uri, media_bytes=raw)]
            self.update_media_stats(doc.media[0])
            yield doc


class ImageConverter(Contracted, PipelineStep):
    """Converts each page's delivered image with an image engine and writes it, decoding and encoding as many pages at
    once as keeps the machine busy without overloading it.

    The preset says what: ``working-image@1`` (engine ``image.webp-lossless.v1``) the working image, 8-bit sRGB
    lossless WebP at full resolution; an ``image.convert.v1`` preset JPEG, JPEG 2000, PNG or WebP
    (``linecaster.images.transcode``: decoded on a GPU where the machine has one and it supports the format, encoded
    there for JPEG and JPEG 2000, else with Pillow; each image records its decoder and encoder). The image is written
    to ``<output_folder>/<item_id>/<page_id>.<ext>`` (``_/<page_id>.<ext>`` for a page without item) under a
    temporary name (``.part``), renamed when complete; with ``skip_existing`` a page whose file is there already is
    not converted again (stat ``existing``): its record names the file, its size read from the header.
    ``page.image`` becomes the converted image's ``PageImage`` (size, hashes, decoder; the encoder, the original
    and the step under ``extra``): it reads and replaces ``metadata``, and with ``keep_bytes`` replaces ``image``;
    without it, it removes ``image``. A page without an image address, over the size limit (``check_size``) or that
    cannot be read or converted keeps its image and carries the reason as an error (field ``image``), so later model
    blocks pass it by and the ``RejectWriter`` writes it; the run goes on.

    Pages go through two stages in threads, each with a window of its own that saturate's controller (``Auto``)
    adapts: decoding (reading the file and decoding it; a GPU batches the decodes that arrive together) and encoding
    (encoding and writing). A window grows while the throughput (pixels per second) still rises and shrinks when the
    machine's memory or this process's open files run short (``Pressure``, saturate's ``kv`` gauge); ``window`` fixes
    both instead. With an engine that does both steps in one call (``image.webp-lossless.v1``) the encoding stage
    only writes. Each worker process uses one GPU (its worker index, round robin), so a machine's GPUs take one
    worker each. Pages leave the block in the order they came in; at most twice the largest window is read ahead.

    Args:
        output_folder: the folder (local path, fsspec URI or ``DataFolder``) the images go to.
        preset: the image preset (``id@edition``, e.g. ``working-image@1``) or an engine spec
            (``InProcess("module:Class", **options)``).
        keep_bytes: the converted image replaces ``doc.media``, so later blocks need not read it again (it then also
            replaces ``image``); without it the page leaves with no image bytes.
        options: engine options over the preset's (recorded as the backend's ``overrides``).
        skip_existing: a page whose file exists is not converted again (a run that resumes).
        window: pages in flight per stage, fixed; None: adapted (``initial_window`` to ``max_window``).
        initial_window: the windows' start.
        max_window: the windows' upper bound (None: twice the CPUs, divided among the worker processes an executor
            runs at once, at least 4).
    """

    type = "🔠 - LINECASTER"
    name = "🖼️ image converter"
    step = "image"
    docs_args = {"output_folder": "out/images", "preset": "working-image@1"}
    # whether the image also travels on in memory, and how many pages are in flight: the same files
    operational = ("keep_bytes", "skip_existing", "window", "initial_window", "max_window")

    def __init__(self, output_folder: DataFolderLike, preset, keep_bytes: bool = False, options: dict | None = None,
                 skip_existing: bool = True, window: int | None = None, initial_window: int = 8,
                 max_window: int | None = None):
        super().__init__()
        self.output_folder, self.keep_bytes = output_folder, keep_bytes
        self.backend = rule_backend(preset, self.step, options)
        self.options = dict(options or {})
        self.skip_existing, self.window = skip_existing, window
        self.initial_window, self.max_window = initial_window, max_window

    def init_params(self) -> dict:
        out = super().init_params()
        out["preset"] = self.backend
        return out

    def warm_up(self) -> None:
        self.backend.warm_up()

    def contract(self) -> Contract:
        """The converted image replaces the page image with ``keep_bytes``; without it the page leaves with no image
        bytes (it removes ``image``)."""
        return Contract(unit="page", role=self.role, reads=parts(("metadata",), None),
                        replaces=parts(("image", "metadata") if self.keep_bytes else ("metadata",), None),
                        removes=parts(() if self.keep_bytes else ("image",), None))

    def _reject(self, doc, stat: str, error: str, error_type: str, raw_value=None, **extra):
        record_error(doc, error_entry(self, error, error_type, field="image", raw_value=raw_value, **extra))
        self.stat_update(stat)
        return doc

    # ----------------------------------------------------------------- one page, in the stages' threads
    def _decode(self, doc, engine, out, ext: str, device: int) -> tuple:
        """The decoding stage: ``("existing", rel, size)``, ``("reject", stat, error, type, raw_value, extra)`` or
        ``("decoded", rel, raw, decoded or (bytes, info), start, began)``."""
        page = page_of(doc)
        src = page.image.uri if page.image else None
        if not src:
            return ("reject", "rejected", "no image location", "missing", None, {})
        rel = f"{page.item_id or '_'}/{doc.id}.{ext}"
        try:
            if self.skip_existing and rel.rsplit("/", 1)[1] in self._listing(out, rel.rsplit("/", 1)[0]):
                from ...images import open_image

                with out.open(rel, "rb") as f, open_image(f.read()) as im:
                    return ("existing", rel, im.size)
            raw = (next((m.media_bytes for m in doc.media if m.media_bytes is not None), None)
                   or read_uri(src, doc.id, page.metadata))
            start, began = now()
            staged = hasattr(engine, "decode")
            done = engine.decode(raw, device) if staged else engine(raw)
            return ("decoded", rel, raw, done, start, began)
        except ImageTooLarge as e:
            return ("reject", "rejected_too_large", e.reason, "ImageTooLarge", src,
                    {"width": e.width, "height": e.height})
        except Exception as e:  # noqa: BLE001 - an undecodable or unreadable delivery: the page's error
            return ("reject", "rejected_unreadable", f"cannot convert: {type(e).__name__}: {e}", type(e).__name__,
                    src, {})

    def _listing(self, out, folder: str) -> frozenset[str]:
        """The file names in ``folder`` of the output, listed once per folder and run (fsspec's file systems, the
        Hub's among them, are not safe to ask from many threads at once); none for a folder that is not there."""
        with self._listings_lock:
            if folder not in self._listings:
                try:
                    names = frozenset(p.rsplit("/", 1)[-1] for p in out.ls(folder, detail=False))
                except (FileNotFoundError, KeyError):
                    names = frozenset()
                self._listings[folder] = names
            return self._listings[folder]

    def _encode(self, decoded: tuple, engine, out, device: int) -> tuple:
        """The encoding stage: ``("converted", rel, raw, data, info, step)`` with the file written, or a reject."""
        _, rel, raw, done, start, began = decoded
        try:
            data, info = engine.encode(done, device) if hasattr(engine, "encode") else done
            step = stamp(engine.step_info(), self.backend, start, began)
            if _object_storage(out):              # an object appears only when its upload is complete
                with out.open(rel, "wb") as f:
                    f.write(data)
            else:
                tmp = f"{rel}.part"
                with out.open(tmp, "wb") as f:
                    f.write(data)
                out.mv(tmp, rel)
            return ("converted", rel, raw, data, info, step)
        except Exception as e:  # noqa: BLE001 - an image that cannot be encoded or written: the page's error
            return ("reject", "rejected_unreadable", f"cannot convert: {type(e).__name__}: {e}", type(e).__name__,
                    rel, {})

    def _finish(self, doc, result: tuple, out, ext: str):
        """The page with what its stages did (in the pipeline's thread: stats and records)."""
        page = page_of(doc)
        self.stat_update("pages")
        kind = result[0]
        if kind == "reject":
            _, stat, error, error_type, raw_value, extra = result
            return self._reject(doc, stat, error, error_type, raw_value, **extra)
        if kind == "existing":
            _, rel, (w, h) = result
            uri = out.resolve_paths(rel)
            original = page.image.model_dump(mode="json", exclude_none=True) if page.image else None
            page.image = PageImage(uri=uri, format=ext, width=w, height=h, extra={"original": original,
                                                                                    "existing": True})
            set_page(doc, page)
            doc.media = []
            self.stat_update("existing")
            return doc
        _, rel, raw, data, info, step = result
        src = page.image.uri if page.image else None
        original = {"uri": src, "format": info["source_format"] or (page.image.format if page.image else None),
                    "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "mode": info["source_mode"],
                    "width": page.image.width if page.image else None,
                    "height": page.image.height if page.image else None}
        extra = {"original": original, "step": step.model_dump(mode="json", exclude_none=True)}
        for k in ("webp_settings", "encoder", "bytes", "icc_applied", "alpha_flattened", "exif_orientation",
                  "icc_error", "warnings"):
            if k in info:
                extra[k] = info[k]
        if info.get("warnings"):
            self.stat_update("image_warnings")
            logger.warning("page {page_id}: converted, with image warnings: {warnings}", page_id=doc.id,
                           warnings="; ".join(info["warnings"]))
        uri = out.resolve_paths(rel)
        page.image = PageImage(uri=uri, format=info["format"], width=info["width"], height=info["height"],
                               sha256=info["sha256"], pixels_sha256=info["pixels_sha256"],
                               decoder=info["decoder"], extra=extra)
        set_page(doc, page)
        doc.media = ([Media(id=doc.id, type=MediaType.IMAGE, url=uri, media_bytes=data)] if self.keep_bytes
                     else [])
        self.stat_update("converted")
        self.stat_update(f"from_{original['format']}")
        if "encoder" in info:
            self.stat_update("gpu_decoded" if "GPU" in info["decoder"] else "cpu_decoded")
            self.stat_update("gpu_encoded" if "GPU" in info["encoder"] else "cpu_encoded")
        return doc

    # ----------------------------------------------------------------- the stages
    def run(self, data, rank: int = 0, world_size: int = 1):
        from ...broker import _WORKER_INDEX
        from ...images import accel

        out = get_datafolder(self.output_folder)
        self._listings, self._listings_lock = {}, threading.Lock()
        engine = self.backend.model()
        ext = engine.extension() if hasattr(engine, "extension") else "webp"
        index, workers = _WORKER_INDEX[0] or (0, 1)
        device = accel.device_for(index)
        results: queue.Queue = queue.Queue()
        top = self.max_window or max(4, 2 * (os.cpu_count() or 1) // workers)     # the CPUs shared by the workers
        windows = {"top": top}
        ahead = threading.Semaphore(2 * top)             # pages read and not yet left the block

        def worker():
            try:
                asyncio.run(self._pump(iter(data), engine, out, ext, device, results, windows, ahead))
            except BaseException as e:  # noqa: BLE001 - surfaced in the pipeline's thread
                results.put(e)
            results.put(_END)

        started = time.perf_counter()
        threading.Thread(target=worker, name="linecaster-image", daemon=True).start()
        waiting, nxt = {}, 0
        while (item := results.get()) is not _END:
            if isinstance(item, BaseException):
                raise item
            seq, doc, result = item
            waiting[seq] = (doc, result)
            while nxt in waiting:                        # in the input's order
                doc, result = waiting.pop(nxt)
                nxt += 1
                ahead.release()
                yield self._finish(doc, result, out, ext)
        self.stat_update("wall_seconds", value=round(time.perf_counter() - started, 2))
        for stage in ("decode", "encode"):
            if stage in windows:
                self.stat_update(f"{stage}_window_max", value=windows[stage])

    def _limiter(self, top: int):
        from saturate import AdaptiveLimiter, Auto, Fixed

        window = Fixed(self.window) if self.window else Auto(initial=min(self.initial_window, top), min_limit=1,
                                                             max_limit=top)
        return AdaptiveLimiter(window=window, signals=Pressure())

    async def _pump(self, docs, engine, out, ext: str, device: int, results: queue.Queue, windows: dict,
                    ahead: threading.Semaphore):
        """Each page through the decoding and the encoding stage, each under its own window; results onto
        ``results`` with the page's place in the input, as they finish. A page is read when ``ahead`` has room (the
        pipeline's thread frees it as the page leaves)."""
        from saturate import Attempt

        top = windows["top"]
        decode, encode = self._limiter(top), self._limiter(top)
        loop = asyncio.get_running_loop()
        end = object()
        failed: list[BaseException] = []

        with ThreadPoolExecutor(max_workers=2 * top, thread_name_prefix="linecaster-image") as pool:

            async def one(seq, doc):
                try:
                    t0 = time.perf_counter()
                    async with decode.slot():
                        decoded = await loop.run_in_executor(pool, self._decode, doc, engine, out, ext, device)
                    if decoded[0] != "decoded":
                        decode.observe(Attempt(ok=decoded[0] == "existing", latency_s=time.perf_counter() - t0))
                        results.put((seq, doc, decoded))
                        return
                    done = decoded[3]
                    rgb = getattr(done, "rgb", None)
                    kpx = (rgb.width * rgb.height if rgb is not None else done[1]["width"] * done[1]["height"]) // 1000
                    decode.observe(Attempt(ok=True, latency_s=time.perf_counter() - t0, tokens=kpx))
                    t1 = time.perf_counter()
                    async with encode.slot():
                        result = await loop.run_in_executor(pool, self._encode, decoded, engine, out, device)
                    encode.observe(Attempt(ok=result[0] == "converted", latency_s=time.perf_counter() - t1,
                                           tokens=kpx))
                    results.put((seq, doc, result))
                except BaseException as e:  # noqa: BLE001 - the stages' own bug: surfaced in the pipeline's thread
                    failed.append(e)
                    results.put(e)
                finally:
                    windows["decode"] = max(windows.get("decode", 0), decode.limit)
                    windows["encode"] = max(windows.get("encode", 0), encode.limit)

            async with decode, encode:
                tasks, seq = set(), 0
                while not failed:                        # after a bug in a stage nothing more is read
                    await loop.run_in_executor(pool, ahead.acquire)
                    doc = await loop.run_in_executor(pool, next, docs, end)
                    if doc is end:
                        break
                    task = asyncio.create_task(one(seq, doc))
                    seq += 1
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                if tasks:                                # every page in flight ends before the threads stop
                    await asyncio.gather(*tasks, return_exceptions=True)


_END = object()


def _object_storage(out) -> bool:
    """Whether ``out`` (a ``DataFolder``) is on object storage (S3, the Hub's buckets, ...), where a file is seen only
    once its upload is complete, so it needs no temporary name (a rename there is a copy)."""
    protocol = getattr(out.fs, "protocol", "file")
    protocols = protocol if isinstance(protocol, tuple | list) else (protocol,)
    return not any(p in ("file", "local", "memory") for p in protocols)


class Pressure:
    """saturate's gauge for the image stages: the share of the machine's memory in use and of this process's open
    files, whichever is higher, as ``kv`` (``Auto`` halves a window at 0.9). None where it cannot be read."""

    async def read(self) -> dict | None:
        shares = [s for s in (_memory_share(), _files_share()) if s is not None]
        return {"kv": max(shares)} if shares else None


def _memory_share() -> float | None:
    try:
        with open("/proc/meminfo") as f:
            info = {line.split(":")[0]: int(line.split()[1]) for line in f if line.split()[1:]}
        return 1 - info["MemAvailable"] / info["MemTotal"]
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        return None


def _files_share() -> float | None:
    try:
        import resource

        soft = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
        return len(os.listdir("/proc/self/fd")) / soft if soft > 0 else None
    except (OSError, ValueError, ImportError):
        return None
