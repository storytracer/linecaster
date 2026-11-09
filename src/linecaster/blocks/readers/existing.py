"""``ExistingImages``: the page images an earlier launch already wrote, so a harvest that is resumed does not fetch
them again. ``ImageFilesWriter`` writes ``<item_id>/<page_id>.<ext>``; a reader with ``reuse_folder`` lists an item's
folder once, when it reaches the item (one fsspec listing: names and sizes), and reads a page whose file is there
from the storage instead of fetching it from the source (``Reused``). Its record is complete (``sha256``, width,
height, as for a download) and says ``image.extra["reused"]``. Only pages of items whose task was interrupted are
read back (with one item per task, at most one item per worker and restart), so storage egress stays small.

A listing never holds a worker up for long: it runs in a thread of its own and the reader waits for it at most
``LISTING_TIMEOUT`` seconds. On object storage fsspec is also given the timeout (its ``sync`` then wraps the listing
in ``asyncio.wait_for`` on its IO loop, which cancels it there, and gives up waiting itself), so a listing that hangs
leaves neither its thread nor fsspec's loop busy; a filesystem without an event loop gets only the wait, and a listing
that never returns keeps its (daemon) thread, which nobody waits for. A listing that times out or fails is one WARNING
(the folder, the time) and a stat (``reuse_listing_timeouts``, ``reuse_listing_errors``), and the item counts as
having nothing to reuse: its pages are fetched again and their files overwritten, which is safe.
"""
from __future__ import annotations

import posixpath
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future

from datatrove.io import DataFolderLike, get_datafolder
from loguru import logger

#: the items whose listings a reader keeps (one item per task in the harvest; a few for tables whose items alternate)
KEPT_ITEMS = 8
#: the longest a reader waits for an item's listing (seconds) before it fetches the item's pages again
LISTING_TIMEOUT = 60.0


class ExistingImages:
    """The image files in ``folder`` by item and page id, an item's folder listed once (the last ``KEPT_ITEMS``
    kept), each listing waited for at most ``listing_timeout`` seconds (None: ``LISTING_TIMEOUT``). Pages without an
    item are never looked up (that would list the whole folder)."""

    def __init__(self, folder: DataFolderLike, listing_timeout: float | None = None):
        self.folder = folder
        self.listing_timeout = listing_timeout
        self._df = None
        self._items: dict[str, dict[str, tuple[str, int, str]]] = {}

    def __getstate__(self):                      # a listing belongs to the task that made it
        return {"folder": self.folder, "listing_timeout": self.listing_timeout, "_df": None, "_items": {}}

    def get(self, item_id: str | None, page_id: str,
            stat: Callable[[str], None] | None = None) -> tuple[str, int, str] | None:
        """``(uri, size, extension)`` of the page's file, or None. ``stat`` (a block's ``stat_update``) counts a
        listing that timed out (``reuse_listing_timeouts``) or failed (``reuse_listing_errors``)."""
        if not item_id:
            return None
        files = self._items.get(item_id)
        if files is None:
            files = self._items[item_id] = self._list(item_id, stat)
            while len(self._items) > KEPT_ITEMS:
                self._items.pop(next(iter(self._items)))
        return files.get(page_id)

    def _list(self, item_id: str, stat: Callable[[str], None] | None = None) -> dict[str, tuple[str, int, str]]:
        if self._df is None:
            self._df = get_datafolder(self.folder)
        timeout = LISTING_TIMEOUT if self.listing_timeout is None else self.listing_timeout
        started = time.monotonic()
        try:
            entries = self._ls(item_id, timeout)
        except FileNotFoundError:
            return {}
        except Exception as e:  # noqa: BLE001 - nothing to reuse: the pages are fetched again
            folder, seconds = self._df.resolve_paths(item_id), time.monotonic() - started
            if isinstance(e, TimeoutError):                     # ours, or fsspec's FSTimeoutError
                logger.warning("listing {folder} for files to reuse took over {seconds:.0f} s; its pages are fetched "
                               "again", folder=folder, seconds=seconds)
            else:
                logger.warning("listing {folder} for files to reuse failed after {seconds:.1f} s: {error}; its pages "
                               "are fetched again", folder=folder, seconds=seconds, error=e)
            if stat is not None:
                stat("reuse_listing_timeouts" if isinstance(e, TimeoutError) else "reuse_listing_errors")
            return {}
        out = {}
        for e in entries:
            if e.get("type", "file") != "file":
                continue
            name = posixpath.basename(e["name"].rstrip("/"))
            stem, dot, ext = name.rpartition(".")
            if not dot or ext == "part":            # a file still being written (``ImageFilesWriter``, local)
                continue
            out[stem] = (self._df.resolve_paths(f"{item_id}/{name}"), int(e.get("size") or 0), ext.lower())
        return out

    def _ls(self, item_id: str, timeout: float) -> list[dict]:
        """The item folder's entries, listed in a daemon thread of its own and waited for at most ``timeout`` seconds
        (``TimeoutError`` then; the thread is left to end, or not, by itself). An async filesystem (object storage)
        gets the timeout too: fsspec's ``sync`` cancels the listing on its loop and raises ``FSTimeoutError``."""
        kwargs = {"detail": True, "refresh": True}
        if getattr(self._df.fs, "async_impl", False):
            kwargs["timeout"] = timeout
        future: Future = Future()

        def run():
            try:
                future.set_result(self._df.ls(item_id, **kwargs))
            except BaseException as e:  # noqa: BLE001 - handed to the waiting reader
                future.set_exception(e)

        threading.Thread(target=run, name="linecaster-reuse-listing", daemon=True).start()
        return future.result(timeout=timeout)


class Reused:
    """What a reader's request window holds for a page whose file is already there: the copy and its bytes, read from
    the storage instead of fetched from the source."""

    def __init__(self, copy: tuple[str, int, str], data: bytes):
        self.copy, self.data = copy, data


def mark_reused(doc) -> None:
    """Mark a page read from its existing file (``image.extra["reused"]``): ``ImageFilesWriter`` does not write it
    again, and the console counts it apart from the downloads."""
    from ..base.page import page_of, set_page

    page = page_of(doc)
    page.image.extra["reused"] = True
    set_page(doc, page)


def is_reused(doc) -> bool:
    """Whether ``doc`` is a page read from its existing image file (``mark_reused``), or a resource read back from its
    copy (``linecaster.blocks.readers.resources``)."""
    from ...data.page import PAGE_KEY

    resource = doc.metadata.get("resource")
    if resource is not None:
        return bool(resource.get("reused"))
    page = doc.metadata.get(PAGE_KEY) or {}
    return bool(((page.get("image") or {}).get("extra") or {}).get("reused"))
