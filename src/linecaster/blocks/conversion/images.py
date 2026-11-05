"""Media blocks: loading page images by URI, and the working image (lossless WebP).

* ``ImageFetcher`` reads ``page.image.uri`` (any fsspec path) into ``doc.media`` for blocks that need
  pixels (``PageRecordReader(fetch_images=False)`` plus ``ImageFetcher`` after filtering avoids fetching
  images of pages that are dropped anyway).
* ``ImageConverter`` converts the delivered image with ``linecaster.images.convert.to_working_webp`` (8-bit
  sRGB, lossless WebP at full resolution, method 0, exact), writes it to
  ``<output_folder>/<item_id>/<page_id>.webp`` and replaces ``page.image`` with the working image's
  ``PageImage`` (size, hashes, decoder); the delivered file is only read, its location, format,
  sha256, size and mode stay under ``page.image.extra["original"]``. A page over the size limit
  (``check_size``) or that cannot be decoded keeps its image and carries the reason as an error (field ``image``),
  so later model blocks pass it by and the rejects writer writes it. With ``keep_bytes`` the WebP replaces
  ``doc.media`` so later blocks need not read it again.
"""
from __future__ import annotations

import hashlib

from datatrove.data import Media, MediaType
from datatrove.io import DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep

from ...data.page import PageImage
from ...images.convert import ImageTooLarge, to_working_webp
from ..base.contract import Contract, Contracted, parts
from ..base.page import error_entry, page_of, record_error, set_page


def read_uri(uri: str) -> bytes:
    import fsspec

    with fsspec.open(uri.split("#", 1)[0], "rb") as f:
        return f.read()


class ImageFetcher(Contracted, PipelineStep):
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
    type = "🔠 - LINECASTER"
    name = "🖼️ image converter (lossless WebP)"
    operational = ("keep_bytes",)          # whether the WebP also travels on in memory: the same files

    def __init__(self, output_folder: DataFolderLike, effort: int = 80, keep_bytes: bool = False):
        super().__init__()
        self.output_folder, self.effort, self.keep_bytes = output_folder, effort, keep_bytes

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
                    webp, info = to_working_webp(raw, effort=self.effort)
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
                     "icc_applied": info["icc_applied"], "alpha_flattened": info["alpha_flattened"]}
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
