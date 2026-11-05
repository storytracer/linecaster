"""The base of linecaster's blocks: one page per datatrove ``Document``.

``doc.id`` is the page id, ``doc.media[0]`` holds the page image's bytes, ``doc.metadata["page"]`` the
page record (``Page`` as a JSON-compatible dict), and ``doc.text`` the text of the page's primary
transcription once there is one.
"""
from __future__ import annotations

import io

from datatrove.data import Document, Media, MediaType
from datatrove.pipeline.base import PipelineStep

from ...data.page import PAGE_KEY, Page, PageImage
from .contract import Contracted


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


class PageBlock(Contracted, PipelineStep):
    """A block that works on pages, in one of two shapes:

    * **per-unit transform** (``shape = "unit"``): subclasses implement ``process_page(doc, page) -> page | None``;
      this class owns the loop and the stats;
    * **stream transform** (``shape = "stream"``): subclasses override ``run(data)`` and yield each page when it is
      done, possibly out of order (served model blocks with their window). They report what happens to each page
      inside the block through ``notify`` (the observers' ``on_unit``).

    The builder installs the observers (``linecaster.runtime.observers``): its boundary steps between blocks call
    ``on_enter`` and ``on_exit`` for every page; ``notify`` reaches them from inside a block. Neither shape sees
    tasks: ``rank`` and ``world_size`` are for readers and writers. The contract (``contract()``) comes from the
    class attributes of ``Contracted`` unless a block computes it."""

    type = "🔠 - LINECASTER"
    shape = "unit"
    #: the observers the builder installed (``linecaster.runtime.observers.Observers``); None: none
    _observers = None

    def notify(self, doc: Document, event: str, **attributes) -> None:
        """Tell the observers about ``event`` for ``doc`` inside this block (``on_unit``); a no-op without any."""
        if self._observers is not None:
            self._observers.on_unit(self, doc, event, **attributes)

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
