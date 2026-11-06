"""``CharacterNormalizer``: character fidelity *as written* -> *normalized*, on ``Line.normalized``,
``Paragraph.normalized`` and the table cells' ``normalized`` (``normalization.*`` engines;
``normalization.latin-historic.v1`` is the mapping table of ``linecaster.text.variants``). The as-written texts are
never touched."""
from __future__ import annotations

from typing import Any

from ...errors import PipelineConfigError
from ..base.contract import Contract, parts
from ..base.item import item_pages, set_item_pages
from ..base.rule import RuleBlock

UNITS = ("page", "item")


class CharacterNormalizer(RuleBlock):
    """Normalizes the texts of every line, paragraph and table cell by a normalization engine, next to the text as
    written.

    Character fidelity *as written* -> *normalized*: each gets its ``normalized`` (``Line.normalized``,
    ``Paragraph.normalized``, the table cells' ``normalized``); the as-written texts are never touched. After a
    ``Recomposer`` the paragraphs are normalized too. Reads ``text``; adds ``normalized``; stat ``changed``.
    ``unit="page"``: each page; ``unit="item"``: each page of an item record (``linecaster.blocks.base.item``),
    after an item-level ``Recomposer``.

    Args:
        preset: the normalization engine: a preset (e.g. ``latin-historic@1``) or an ``InProcess`` engine spec.
        transcription: the transcription to normalize.
        unit: ``page`` (a stream of pages) or ``item`` (a stream of item records, after a ``Binder``).
        options: engine options over the preset's; ``None``: the preset's.

    Example:
        CharacterNormalizer("latin-historic@1", unit="item")
    """

    name = "character normalizer"
    step = "normalization"
    docs_args = {"preset": "latin-historic@1"}

    def __init__(self, preset, transcription: str = "ocr_new", unit: str = "page",
                 options: dict[str, Any] | None = None):
        if unit not in UNITS:
            raise PipelineConfigError(f"character normalizer: unit {unit!r}; choose {', '.join(UNITS)}")
        self.unit = unit
        super().__init__(preset, transcription, options)

    def contract(self) -> Contract:
        return Contract(unit=self.unit, role=self.role, reads=parts(("text",), self.transcription),
                        adds=parts(("normalized",), self.transcription))

    def apply(self, page, t) -> None:
        self.engine(t)
        self.count(t.steps[-1].measurements, ("changed",))

    def run(self, data, rank: int = 0, world_size: int = 1):
        if self.unit == "page":
            yield from super().run(data, rank, world_size)
            return
        for doc in data:
            self.stat_update("items")
            with self.track_time():
                pages = [self.process_page(doc, page) for page in item_pages(doc)]
                set_item_pages(doc, pages)
            yield doc
