"""``ExistingImages``: the page images an earlier launch already wrote, so a harvest that is resumed does not fetch
them again. ``ImageFilesWriter`` writes ``<item_id>/<page_id>.<ext>``; a reader with ``reuse_folder`` lists an item's
folder once, when it reaches the item (one fsspec listing: names and sizes, no contents, so no egress on any
storage), and passes a page whose file is there on without a request (``reused_page``). Its record names the copy and
says ``image.extra["reused"]``; ``sha256``, width and height stay empty, since the bytes are not read.
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
    """What a reader's request window holds for a page whose file is already there: the copy, no request."""

    def __init__(self, copy: tuple[str, int, str]):
        self.copy = copy


def reused_page(page_id: str, copy: tuple[str, int, str], source_uri: str | None, item_id: str | None,
                sequence: int | None, metadata: dict):
    """The document of a page whose image file is already there: no image bytes; ``image.uri`` the copy,
    ``image.extra`` its ``source_uri``, ``reused`` and the file's ``bytes``; the format from the extension."""
    from datatrove.data import Document

    from ...data.page import Page, PageImage
    from ..base.page import set_page
    from ..writers.images import IMAGE_FILE_EXTENSIONS

    uri, size, ext = copy
    formats = {v: k for k, v in IMAGE_FILE_EXTENSIONS.items()}
    image = PageImage(uri=uri, format=formats.get(ext, ext), extra={"source_uri": source_uri, "reused": True,
                                                                    "bytes": size})
    doc = Document(text="", id=page_id, media=[])
    set_page(doc, Page(page_id=page_id, item_id=item_id, sequence=sequence, image=image, metadata=metadata))
    return doc


def is_reused(doc) -> bool:
    """Whether ``doc`` is a page passed on from its existing image file (``reused_page``)."""
    from ...data.page import PAGE_KEY

    page = doc.metadata.get(PAGE_KEY) or {}
    return bool(((page.get("image") or {}).get("extra") or {}).get("reused"))
