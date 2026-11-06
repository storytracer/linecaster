"""Image blocks: page images loaded again by their address (``ImageFetcher``), and the working image, lossless
WebP at full resolution (``ImageConverter``)."""
from __future__ import annotations

import hashlib

from datatrove.data import Media, MediaType
from datatrove.io import DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep

from ...data.page import PageImage
from ...images.convert import ImageTooLarge
from ..base.contract import Contract, Contracted, parts
from ..base.page import error_entry, page_of, record_error, set_page
from ..base.rule import now, rule_backend, stamp


def read_uri(uri: str) -> bytes:
    import fsspec

    with fsspec.open(uri.split("#", 1)[0], "rb") as f:
        return f.read()


class ImageFetcher(Contracted, PipelineStep):
    """Loads each page's image again from its address, for the blocks that need pixels.

    It reads ``page.image.uri`` (any fsspec path; a ``#`` fragment is dropped) into ``doc.media``: it replaces
    ``image``. ``PageRecordReader(fetch_images=False)`` followed by an ``ImageFetcher`` after filtering avoids
    fetching the images of pages that are dropped anyway. A page without an image address is counted
    (``no_image``) and passed on as it is.
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
            with self.track_time():
                raw = read_uri(page.image.uri)
            doc.media = [Media(id=doc.id, type=MediaType.IMAGE, url=page.image.uri, media_bytes=raw)]
            self.update_media_stats(doc.media[0])
            yield doc


class ImageConverter(Contracted, PipelineStep):
    """Converts each page's delivered image into the working image with an image engine and writes it.

    With ``working-image@1`` (engine ``image.webp-lossless.v1``, ``linecaster.images.convert.to_working_webp``)
    the working image is 8-bit sRGB, lossless WebP at full resolution, method 0, exact. It is written to
    ``<output_folder>/<item_id>/<page_id>.webp`` (``_/<page_id>.webp`` for a page without item), and
    ``page.image`` becomes the working image's ``PageImage`` (size, hashes, decoder): it reads and replaces
    ``metadata``. The delivered file is only read (from ``doc.media`` when the reader brought it, else from its
    URI); its location, format, sha256, size and mode stay under ``page.image.extra["original"]``, the step
    (engine, preset edition and hash, settings) under ``page.image.extra["step"]`` (a ``StepInfo``: the image
    belongs to no transcription). A page without an image address, over the size limit (``check_size``) or that
    cannot be decoded keeps its image and carries the reason as an error (field ``image``), so later model blocks
    pass it by and the ``RejectWriter`` writes it. The engine runs in the pipeline's process only.

    Args:
        output_folder: the folder (local path, fsspec URI or ``DataFolder``) the working images go to.
        preset: the image preset (``id@edition``, e.g. ``working-image@1``) or an engine spec
            (``InProcess("module:Class", **options)``).
        keep_bytes: the WebP replaces ``doc.media``, so later blocks need not read it again (it then also
            replaces ``image``); without it the page leaves with no image bytes.
        options: engine options over the preset's (recorded as the backend's ``overrides``).
    """

    type = "🔠 - LINECASTER"
    name = "🖼️ image converter (lossless WebP)"
    step = "image"
    docs_args = {"output_folder": "out/images", "preset": "working-image@1"}
    operational = ("keep_bytes",)          # whether the WebP also travels on in memory: the same files

    def __init__(self, output_folder: DataFolderLike, preset, keep_bytes: bool = False, options: dict | None = None):
        super().__init__()
        self.output_folder, self.keep_bytes = output_folder, keep_bytes
        self.backend = rule_backend(preset, self.step, options)
        self.options = dict(options or {})

    def init_params(self) -> dict:
        out = super().init_params()
        out["preset"] = self.backend
        return out

    def warm_up(self) -> None:
        self.backend.warm_up()

    def contract(self) -> Contract:
        """The working image replaces the page image (its bytes travel on only with ``keep_bytes``)."""
        return Contract(unit="page", role=self.role, reads=parts(("metadata",), None),
                        replaces=parts(("image", "metadata") if self.keep_bytes else ("metadata",), None))

    def _reject(self, doc, stat: str, error: str, error_type: str, raw_value=None, **extra):
        record_error(doc, error_entry(self, error, error_type, field="image", raw_value=raw_value, **extra))
        self.stat_update(stat)
        return doc

    def run(self, data, rank: int = 0, world_size: int = 1):
        out = get_datafolder(self.output_folder)
        for doc in data:
            page = page_of(doc)
            self.stat_update("pages")
            src = page.image.uri if page.image else None
            if not src:
                yield self._reject(doc, "rejected", "no image location", "missing")
                continue
            try:
                with self.track_time("read"):
                    raw = next((m.media_bytes for m in doc.media if m.media_bytes is not None), None) or read_uri(src)
                with self.track_time("convert"):
                    start, began = now()
                    engine = self.backend.model()
                    webp, info = engine(raw)
                    step = stamp(engine.step_info(), self.backend, start, began)
            except ImageTooLarge as e:
                yield self._reject(doc, "rejected_too_large", e.reason, "ImageTooLarge", src, width=e.width,
                                   height=e.height)
                continue
            except Exception as e:      # an undecodable or unreadable delivery
                yield self._reject(doc, "rejected_unreadable", f"cannot convert: {type(e).__name__}: {e}",
                                   type(e).__name__, src)
                continue
            rel = f"{page.item_id or '_'}/{doc.id}.webp"
            with out.open(rel, "wb") as f:
                f.write(webp)
            original = {"uri": src, "format": info["source_format"] or (page.image.format if page.image else None),
                        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "mode": info["source_mode"],
                        "width": page.image.width if page.image else None,
                        "height": page.image.height if page.image else None}
            extra = {"original": original, "webp_settings": info["webp_settings"],
                     "icc_applied": info["icc_applied"], "alpha_flattened": info["alpha_flattened"],
                     "step": step.model_dump(mode="json", exclude_none=True)}
            for k in ("exif_orientation", "icc_error"):
                if k in info:
                    extra[k] = info[k]
            uri = out.resolve_paths(rel)
            page.image = PageImage(uri=uri, format="webp", width=info["width"], height=info["height"],
                                   sha256=info["sha256"], pixels_sha256=info["pixels_sha256"],
                                   decoder=info["decoder"], extra=extra)
            set_page(doc, page)
            doc.media = ([Media(id=doc.id, type=MediaType.IMAGE, url=uri, media_bytes=webp)] if self.keep_bytes
                         else [])
            self.stat_update("converted")
            self.stat_update(f"from_{original['format']}")
            yield doc
