"""The base of linecaster's blocks: one page per datatrove ``Document``.

``doc.id`` is the page id, ``doc.media[0]`` holds the page image's bytes, ``doc.metadata["page"]`` the
page row (``Page`` as a JSON-compatible dict), and ``doc.text`` the text of the page's primary
transcription once there is one.
"""
from __future__ import annotations

import io

from datatrove.data import Document, Media, MediaType
from datatrove.pipeline.base import PipelineStep

from ...data.page import PAGE_KEY, Page, PageImage


def page_of(doc: Document) -> Page:
    return Page.model_validate(doc.metadata[PAGE_KEY])


def set_page(doc: Document, page: Page, primary: str | None = None) -> None:
    doc.metadata[PAGE_KEY] = page.model_dump(mode="json")
    if primary and primary in page.transcriptions:
        doc.text = page.transcriptions[primary].text


def image_bytes(doc: Document) -> bytes:
    for m in doc.media:
        if m.type == MediaType.IMAGE and m.media_bytes is not None:
            return m.media_bytes
    raise ValueError(f"page {doc.id} carries no image bytes")


def decode_rgb(data: bytes):
    """The page image as an RGB uint8 array (what every engine backend receives)."""
    import numpy as np
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        return np.asarray(im.convert("RGB"))


def new_page_document(page_id: str, data: bytes, uri: str | None = None, item_id: str | None = None,
                      sequence: int | None = None, metadata: dict | None = None) -> Document:
    """A ``Document`` for a page image read from ``uri``; size and format come from the image header."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        fmt, (w, h) = (im.format or "").lower() or None, im.size
    page = Page(page_id=page_id, item_id=item_id, sequence=sequence,
                image=PageImage(uri=uri, format=fmt, width=w, height=h, sha256=PageImage.digest(data)),
                metadata=metadata or {})
    doc = Document(text="", id=page_id, media=[Media(id=page_id, type=MediaType.IMAGE, url=uri or "", media_bytes=data)])
    set_page(doc, page)
    return doc


class PageBlock(PipelineStep):
    """A block that works on pages. Subclasses implement ``process_page`` (or override ``run``)."""

    type = "🔠 - LINECASTER"

    def process_page(self, doc: Document, page: Page) -> Page | None:  # pragma: no cover - interface
        raise NotImplementedError

    def run(self, data, rank: int = 0, world_size: int = 1):
        for doc in data:
            self.stat_update("pages")
            with self.track_time():
                page = self.process_page(doc, page_of(doc))
            if page is None:
                self.stat_update("dropped")
                continue
            set_page(doc, page, getattr(self, "primary", None))
            yield doc
