"""``RejectSink``: the rejects file every block with rejects shares, ``<folder>/<prefix><rank>.jsonl``, opened
on the first reject (a task without rejects leaves no file): one JSON line per reject with ``key``,
``field``, ``error`` and ``raw_value``, so nothing disappears silently."""
from __future__ import annotations

import json

from datatrove.io import DataFolderLike, get_datafolder


class RejectSink:
    """``write(key, field, error, raw_value, **extra)`` appends one JSON line to
    ``<folder>/<prefix><rank:05d>.jsonl``; ``prefix`` keeps two blocks that share a rejects folder apart."""

    def __init__(self, folder: DataFolderLike, rank: int = 0, prefix: str = ""):
        self.folder, self.name, self._f, self.count = get_datafolder(folder), f"{prefix}{rank:05d}.jsonl", None, 0

    def write(self, key: str, field: str, error: str, raw_value=None, **extra) -> None:
        if self._f is None:
            self._f = self.folder.open(self.name, "wt")
        rec = {"key": key, "field": field, "error": error, "raw_value": raw_value, **extra}
        self._f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self.count += 1

    def close(self) -> None:
        if self._f is not None:
            self._f.close()
            self._f = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
