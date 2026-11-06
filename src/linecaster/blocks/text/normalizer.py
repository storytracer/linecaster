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
    """The normalized texts of the named transcription's lines, paragraphs and table cells by a normalization
    engine (``preset``: e.g. ``latin-historic@1``, or an ``InProcess`` engine spec; ``options`` over it). After a
    ``Recomposer`` the paragraphs are normalized too.

    ``unit="page"``: each page; ``unit="item"``: each page of an item record (``linecaster.blocks.base.item``), after
    an item-level ``Recomposer``."""

    name = "character normalizer"
    step = "normalization"

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
