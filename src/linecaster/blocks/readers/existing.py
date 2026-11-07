"""``ExistingImages``: the page images an earlier launch already wrote, so a harvest that is resumed does not fetch
them again. ``ImageFilesWriter`` writes ``<item_id>/<page_id>.<ext>``; a reader with ``reuse_folder`` lists an item's
folder once, when it reaches the item (one fsspec listing: names and sizes), and reads a page whose file is there
from the storage instead of fetching it from the source (``Reused``). Its record is complete (``sha256``, width,
height, as for a download) and says ``image.extra["reused"]``. Only pages of items whose task was interrupted are
read back (with one item per task, at most one item per worker and restart), so storage egress stays small.
"""
from __future__ import annotations

import posixpath

from datatrove.io import DataFolderLike, get_datafolder

#: the items whose listings a reader keeps (one item per task in the harvest; a few for tables whose items alternate)
KEPT_ITEMS = 8


class ExistingImages:
    """The image files in ``folder`` by item and page id, an item's folder listed once (the last ``KEPT_ITEMS``
    kept). Pages without an item are never looked up (that would list the whole folder)."""

    def __init__(self, folder: DataFolderLike):
        self.folder = folder
        self._df = None
        self._items: dict[str, dict[str, tuple[str, int, str]]] = {}

    def __getstate__(self):                      # a listing belongs to the task that made it
        return {"folder": self.folder, "_df": None, "_items": {}}

    def get(self, item_id: str | None, page_id: str) -> tuple[str, int, str] | None:
        """``(uri, size, extension)`` of the page's file, or None."""
        if not item_id:
            return None
        files = self._items.get(item_id)
        if files is None:
            files = self._items[item_id] = self._list(item_id)
            while len(self._items) > KEPT_ITEMS:
                self._items.pop(next(iter(self._items)))
        return files.get(page_id)

    def _list(self, item_id: str) -> dict[str, tuple[str, int, str]]:
        if self._df is None:
            self._df = get_datafolder(self.folder)
        try:
            entries = self._df.ls(item_id, detail=True, refresh=True)
        except FileNotFoundError:
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
