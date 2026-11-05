"""``PageValidator``: a filter with rejects. A row that fails a check is written to ``rejects/<output>/``
with ``key``, ``field``, ``error`` and ``raw_value`` (``RejectWriter``, so nothing disappears silently) and
dropped: it validates the page row against ``Page`` and checks that required parts are present.
"""
from __future__ import annotations

from datatrove.io import DataFolderLike
from datatrove.pipeline.base import PipelineStep
from pydantic import ValidationError

from ...data.page import PAGE_KEY, Page
from ..writers.rejects import RejectWriter


def has_part(page: Page, part: str) -> bool:
    """``"image"``, ``"item_id"``, ... (a non-empty field) or ``"transcriptions.<name>"``."""
    if part.startswith("transcriptions."):
        return part.split(".", 1)[1] in page.transcriptions
    return getattr(page, part, None) is not None


class PageValidator(PipelineStep):
    """Drop page rows that do not validate against ``Page`` or lack a ``required`` part, with a reject
    record each (field = the failing location, raw value = the offending input)."""

    type = "🔻 - FILTER"
    name = "✅ page validator"

    def __init__(self, rejects_folder: DataFolderLike, required: tuple[str, ...] = (), prefix: str = "validate_"):
        super().__init__()
        self.rejects_folder, self.required, self.prefix = rejects_folder, tuple(required), prefix

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
