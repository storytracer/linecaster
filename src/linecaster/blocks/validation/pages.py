"""``PageValidator``: checks with rejects. It validates the page record against ``Page`` and checks that required
parts are present; a page that fails carries the reason as an error (``field``, ``error``, ``raw_value``), so later
model blocks pass it by and the rejects writer (``RejectWriter``) writes it to ``rejects/``: nothing disappears
silently.
"""
from __future__ import annotations

from datatrove.pipeline.base import PipelineStep
from pydantic import ValidationError

from ...data.page import PAGE_KEY, Page
from ..base.contract import Contract, Contracted, Part
from ..base.page import error_entry, record_error


def has_part(page: Page, part: str) -> bool:
    """``"image"``, ``"item_id"``, ... (a non-empty field) or ``"transcriptions.<name>"``."""
    if part.startswith("transcriptions."):
        return part.split(".", 1)[1] in page.transcriptions
    return getattr(page, part, None) is not None


class PageValidator(Contracted, PipelineStep):
    """Marks the page records that do not validate against ``Page`` or lack a required part with an error each.

    The error entry (``doc.metadata["errors"]``) names the failing location as ``field`` and the offending input as
    ``raw_value`` (type ``invalid``, or ``missing`` for a required part); later model blocks pass such a page by and
    the ``RejectWriter`` writes it to ``rejects/``. It reads what it requires. Every page goes on.

    Args:
        required: what each page must have: a page field (``"image"``, ``"item_id"``, ...: not empty) or a
            transcription (``"transcriptions.<name>"``); default: nothing beyond a valid page record.
    """

    type = "🔠 - LINECASTER"
    name = "✅ page validator"

    def __init__(self, required: tuple[str, ...] = ()):
        super().__init__()
        self.required = tuple(required)

    role = "validator"

    def contract(self) -> Contract:
        """It reads what it requires: a transcription (``transcriptions.<name>``: any part of it) or a page
        field (the page record, ``metadata``; ``"image"`` is the page record's image entry, not its bytes)."""
        reads = frozenset(Part("*", p.split(".", 1)[1]) if p.startswith("transcriptions.") else Part("metadata")
                          for p in self.required)
        return Contract(unit="page", role=self.role, reads=reads)

    def run(self, data, rank: int = 0, world_size: int = 1):
        for doc in data:
            self.stat_update("pages")
            try:
                page = Page.model_validate(doc.metadata.get(PAGE_KEY))
            except ValidationError as e:
                err = e.errors()[0]
                record_error(doc, error_entry(self, err["msg"], "invalid",
                                              field=".".join(map(str, err["loc"])) or PAGE_KEY,
                                              raw_value=err.get("input")))
                self.stat_update("rejected")
                yield doc
                continue
            missing = [p for p in self.required if not has_part(page, p)]
            if missing:
                record_error(doc, error_entry(self, "required part missing", "missing", field=missing[0]))
                self.stat_update("rejected")
            yield doc
