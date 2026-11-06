"""``Typographer``: the typographic hierarchy of a page (``typography.*`` engines; ``typography.ratios.v1`` is
squiddleocr's retyper, ``linecaster.text.typography``)."""
from __future__ import annotations

from ..base.rule import RuleBlock


class Typographer(RuleBlock):
    """The hierarchy of the named transcription by a typography engine (``preset``: e.g. ``ratios@1``, or an
    ``InProcess`` engine spec; ``options`` over it): heading levels from type size, headline splits, drop
    capitals, uncertain page numbers removed (see ``linecaster.text.typography``)."""

    name = "typographer"
    step = "typography"
    parts_read = ("regions", "lines")
    parts_added = ("hierarchy",)
    parts_replaced = ("regions", "lines")      # heading levels, headline splits, page numbers removed

    def apply(self, page, t) -> None:
        self.engine(t)
        self.count(t.steps[-1].measurements, ("leveled", "demoted", "split", "drop_capitals", "numbers_dropped"))
