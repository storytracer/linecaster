"""Media blocks: loading page images by URI, and the working image (lossless WebP).

* ``AttachImage`` reads ``page.image.uri`` (any fsspec path) into ``doc.media`` for blocks that need
  pixels (``PageRowReader(fetch_images=False)`` plus ``AttachImage`` after filtering avoids fetching
  images of pages that are dropped anyway).
* ``WorkingImages`` converts the delivered image with ``linecaster.images.to_working_webp`` (8-bit
  sRGB, lossless WebP at full resolution, method 0, exact), writes it to
  ``<output_folder>/<item_id>/<page_id>.webp`` and replaces ``page.image`` with the working image's
  ``PageImage`` (size, hashes, decoder); the delivered file is only read, its location, format,
  sha256, size and mode stay under ``page.image.extra["original"]``. Pages over the size limit
  (``check_size``) or that cannot be decoded go to ``rejects`` and are dropped. With
  ``keep_bytes`` the WebP replaces ``doc.media`` so later blocks need not read it again.
"""
from __future__ import annotations

import hashlib

from datatrove.data import Media, MediaType
from datatrove.io import DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep

from ..images import ImageTooLarge, to_working_webp
from ..page import PageImage
from .base import page_of, set_page
from .filters import RejectSink


def read_uri(uri: str) -> bytes:
    import fsspec

    with fsspec.open(uri.split("#", 1)[0], "rb") as f:
        return f.read()


class AttachImage(PipelineStep):
    type = "🔠 - LINECASTER"
    name = "🖼️ attach image"

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


class WorkingImages(PipelineStep):
    type = "🔠 - LINECASTER"
    name = "🖼️ working images (lossless WebP)"

    def __init__(self, output_folder: DataFolderLike, rejects_folder: DataFolderLike, effort: int = 80,
                 keep_bytes: bool = False):
        super().__init__()
        self.output_folder, self.rejects_folder = output_folder, rejects_folder
        self.effort, self.keep_bytes = effort, keep_bytes

    def run(self, data, rank: int = 0, world_size: int = 1):
        out = get_datafolder(self.output_folder)
        with RejectSink(self.rejects_folder, rank) as sink:
            for doc in data:
                page = page_of(doc)
                self.stat_update("pages")
                src = page.image.uri if page.image else None
                if not src:
                    sink.write(doc.id, "image", "no image location", None)
                    self.stat_update("rejected")
                    continue
                try:
                    with self.track_time("read"):
                        raw = next((m.media_bytes for m in doc.media if m.media_bytes is not None), None) or read_uri(src)
                    with self.track_time("convert"):
                        webp, info = to_working_webp(raw, effort=self.effort)
                except ImageTooLarge as e:
                    sink.write(doc.id, "image", e.reason, src, width=e.width, height=e.height)
                    self.stat_update("rejected_too_large")
                    continue
                except Exception as e:      # an undecodable or unreadable delivery
                    sink.write(doc.id, "image", f"cannot convert: {type(e).__name__}: {e}", src)
                    self.stat_update("rejected_unreadable")
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
