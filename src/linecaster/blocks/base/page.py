"""The base of linecaster's blocks: one page per datatrove ``Document``.

``doc.id`` is the page id, ``doc.media[0]`` holds the page image's bytes, ``doc.metadata["page"]`` the
page record (``Page`` as a JSON-compatible dict), and ``doc.text`` the text of the page's primary
transcription once there is one.
"""
from __future__ import annotations

import io

from datatrove.data import Document, Media, MediaType
from datatrove.pipeline.base import PipelineStep
from loguru import logger

from ...data.page import PAGE_KEY, Page, PageImage
from ...errors import CatalogError, PageError, PipelineConfigError, ServerError
from .contract import Contracted

#: where a page records what failed on it: a list of entries (``error_entry``)
ERRORS_KEY = "errors"
#: the pages a task processes before its error budget is a share of them (with fewer, the share of this many)
ERROR_GRACE = 100
#: errors that are not the page's: they fail the task at once
NOT_THE_PAGES = (PipelineConfigError, CatalogError, ServerError)


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
    raise PageError(doc.id, message="it carries no image bytes")


def decode_rgb(data: bytes):
    """The page image as an RGB uint8 array (what every engine backend receives)."""
    import numpy as np
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        return np.asarray(im.convert("RGB"))


def failed(doc: Document) -> bool:
    """Whether an earlier block failed on this page (it carries ``doc.metadata["errors"]``)."""
    return bool(doc.metadata.get(ERRORS_KEY))


def error_entry(block, error: BaseException | str, error_type: str | None = None, **extra) -> dict:
    """What a page records when ``block`` fails on it: ``block`` (its class), ``step`` (a model block's), ``preset``
    (its edition, if it has one), ``type`` (the exception's class, or ``error_type``) and ``error`` (the message),
    plus ``extra`` (e.g. ``field`` and ``raw_value`` of a check)."""
    entry = {"block": type(block).__name__}
    if getattr(block, "step", None) and block.step != "model":
        entry["step"] = block.step
    entry["preset"] = getattr(getattr(block, "backend", None), "preset", None)
    entry["type"] = error_type or (type(error).__name__ if isinstance(error, BaseException) else "error")
    entry["error"] = str(error) if isinstance(error, BaseException) else error
    entry.update(extra)
    return entry


def record_error(doc: Document, entry: dict) -> dict:
    """Add ``entry`` to the page's errors; later model blocks pass the page by and the rejects writer writes it."""
    doc.metadata.setdefault(ERRORS_KEY, []).append(entry)
    return entry


class ErrorBudget:
    """The share of a task's pages a block may fail on (``share``, e.g. 0.01) before the task fails, judged from the
    ``ERROR_GRACE``-th page on: from then, more errors than ``share`` of the pages seen fail the task (with 1 %: two
    errors in the first 100 pages, three in 300). Fewer pages than that are too few to judge. ``None``: no limit."""

    def __init__(self, block, share: float | None):
        self.block, self.share, self.pages, self.errors = block, share, 0, 0
        self._last: tuple = ("", None, None)        # page id, block, cause of the latest failure

    def page(self) -> None:
        self.pages += 1
        self._check()

    def failed(self, doc: Document, entry: dict, cause: BaseException | None = None) -> None:
        """One more page failed: logged; a ``PageError`` (it fails the task) once the budget is spent."""
        self.errors += 1
        self.block.stat_update("errors")
        what = "file" if getattr(self.block, "unit_label", "pages") == "files" else "page"   # a resource reader's
        logger.warning("{what} {page_id} failed in {block}: {error_type}: {error}", what=what, page_id=doc.id,
                       block=entry["block"], error_type=entry["type"], error=entry["error"])
        self._last = (doc.id, entry["block"], cause)
        self._check()

    def _check(self) -> None:
        if self.share is None or self.pages < ERROR_GRACE or self.errors <= self.share * self.pages:
            return
        page_id, block, cause = self._last
        raise PageError(page_id, block, f"{self.errors} of {self.pages} pages failed, more than the error budget "
                                        f"(max_page_errors={self.share:g}, judged from page {ERROR_GRACE} on)") from cause


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
    """Processes a stream of pages, one datatrove document per page, as the base of the page blocks.

    A page block has one of two shapes:

    * **per-unit transform** (``shape = "unit"``): subclasses implement ``process_page(doc, page) -> page | None``;
      this class owns the loop and the stats;
    * **stream transform** (``shape = "stream"``): subclasses override ``run(data)`` and yield each page when it is
      done, possibly out of order (served model blocks with their window). They report what happens to each page
      inside the block through ``notify`` (the observers' ``on_unit``).

    The builder installs the observers (``linecaster.runtime.observers``): its boundary steps between blocks call
    ``on_enter`` and ``on_exit`` for every page; ``notify`` reaches them from inside a block. Neither shape sees
    tasks: ``rank`` and ``world_size`` are for readers and writers. The contract (``contract()``) comes from the
    class attributes of ``Contracted`` unless a block computes it.

    **Failures.** An exception in ``process_page`` (other than a pipeline, catalog or server error, which fail the
    task) becomes an entry in the page's ``doc.metadata["errors"]`` (``error_entry``), and the page goes on as it
    was. With ``skip_on_error`` (model blocks) a page that carries errors passes through at once. More failures than
    ``max_page_errors`` (a share of the task's pages, ``ErrorBudget``) fail the task with a ``PageError``."""

    type = "🔠 - LINECASTER"
    shape = "unit"
    #: pass pages an earlier block failed on through at once (model blocks); others process them as any page
    skip_on_error = False
    #: the error budget: the share of a task's pages this block may fail on (None: no limit; the builder sets it)
    max_page_errors: float | None = 0.01

    def notify(self, doc: Document, event: str, **attributes) -> None:
        """Tell the observers about ``event`` for ``doc`` inside this block (``on_unit``); a no-op without any."""
        if self._observers is not None:
            self._observers.on_unit(self, doc, event, **attributes)

    def process_page(self, doc: Document, page: Page) -> Page | None:  # pragma: no cover - interface
        raise NotImplementedError

    def run(self, data, rank: int = 0, world_size: int = 1):
        budget = ErrorBudget(self, self.max_page_errors)
        for doc in data:
            if self.skip_on_error and failed(doc):
                self.stat_update("skipped_after_error")
                yield doc
                continue
            self.stat_update("pages")
            budget.page()
            try:
                with self.track_time():
                    page = self.process_page(doc, page_of(doc))
            except NOT_THE_PAGES:
                raise
            except Exception as e:      # the page's failure: recorded on it, counted against the budget
                budget.failed(doc, record_error(doc, error_entry(self, e)), e)
                yield doc
                continue
            if page is None:
                self.stat_update("dropped")
                continue
            set_page(doc, page, getattr(self, "primary", None))
            yield doc
