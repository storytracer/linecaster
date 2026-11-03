"""Filters with rejects: a row that fails a check is written to ``rejects/<output>/`` with ``key``,
``field``, ``error`` and ``raw_value`` (so nothing disappears silently) and dropped.

``RejectSink`` is the writer every block with rejects shares: ``<folder>/<prefix><rank>.jsonl``, opened
on the first reject (a task without rejects leaves no file). ``ValidatePages`` validates the page row
against ``Page`` and checks that required parts are present.
"""
from __future__ import annotations

import json

from datatrove.io import DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep
from pydantic import ValidationError

from ..page import PAGE_KEY, Page


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


def has_part(page: Page, part: str) -> bool:
    """``"image"``, ``"item_id"``, ... (a non-empty field) or ``"transcriptions.<name>"``."""
    if part.startswith("transcriptions."):
        return part.split(".", 1)[1] in page.transcriptions
    return getattr(page, part, None) is not None


class ValidatePages(PipelineStep):
    """Drop page rows that do not validate against ``Page`` or lack a ``required`` part, with a reject
    record each (field = the failing location, raw value = the offending input)."""

    type = "🔻 - FILTER"
    name = "✅ validate pages"

    def __init__(self, rejects_folder: DataFolderLike, required: tuple[str, ...] = (), prefix: str = "validate_"):
        super().__init__()
        self.rejects_folder, self.required, self.prefix = rejects_folder, tuple(required), prefix

    def run(self, data, rank: int = 0, world_size: int = 1):
        with RejectSink(self.rejects_folder, rank, self.prefix) as sink:
            for doc in data:
                self.stat_update("pages")
                try:
                    page = Page.model_validate(doc.metadata.get(PAGE_KEY))
                except ValidationError as e:
                    err = e.errors()[0]
                    sink.write(doc.id, ".".join(map(str, err["loc"])) or PAGE_KEY, err["msg"], err.get("input"))
                    self.stat_update("rejected")
                    continue
                missing = [p for p in self.required if not has_part(page, p)]
                if missing:
                    sink.write(doc.id, missing[0], "required part missing", None)
                    self.stat_update("rejected")
                    continue
                yield doc
