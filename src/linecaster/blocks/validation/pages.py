"""``PageValidator``: a filter with rejects. A row that fails a check is written to ``rejects/<output>/``
with ``key``, ``field``, ``error`` and ``raw_value`` (``RejectWriter``, so nothing disappears silently) and
dropped: it validates the page record against ``Page`` and checks that required parts are present.
"""
from __future__ import annotations

from datatrove.io import DataFolderLike
from datatrove.pipeline.base import PipelineStep
from pydantic import ValidationError

from ...data.page import PAGE_KEY, Page
from ..base.contract import Contract, Contracted, Part
from ..writers.rejects import RejectWriter


def has_part(page: Page, part: str) -> bool:
    """``"image"``, ``"item_id"``, ... (a non-empty field) or ``"transcriptions.<name>"``."""
    if part.startswith("transcriptions."):
        return part.split(".", 1)[1] in page.transcriptions
    return getattr(page, part, None) is not None


class PageValidator(Contracted, PipelineStep):
    """Drop page records that do not validate against ``Page`` or lack a ``required`` part, with a reject
    record each (field = the failing location, raw value = the offending input)."""

    type = "🔻 - FILTER"
    name = "✅ page validator"

    def __init__(self, rejects_folder: DataFolderLike, required: tuple[str, ...] = (), prefix: str = "validate_"):
        super().__init__()
        self.rejects_folder, self.required, self.prefix = rejects_folder, tuple(required), prefix

    role = "validator"

    def contract(self) -> Contract:
        """It reads what it requires: a transcription (``transcriptions.<name>``: any part of it) or a page
        field (the page record)."""
        reads = frozenset(Part("*", p.split(".", 1)[1]) if p.startswith("transcriptions.")
                          else Part("image" if p == "image" else "metadata") for p in self.required)
        return Contract(unit="page", role=self.role, reads=reads)

    def run(self, data, rank: int = 0, world_size: int = 1):
        with RejectWriter(self.rejects_folder, rank, self.prefix) as sink:
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
