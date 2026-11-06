"""``Typographer``: the typographic hierarchy of a page (``typography.*`` engines; ``typography.ratios.v1`` is
squiddleocr's retyper, ``linecaster.text.typography``)."""
from __future__ import annotations

from ..base.rule import RuleBlock


class Typographer(RuleBlock):
    """Determines the typographic hierarchy of every page by a typography engine.

    Heading levels from type size, headline splits, drop capitals, uncertain page numbers removed (see
    ``linecaster.text.typography``). Reads ``regions`` and ``lines``; adds ``hierarchy``; replaces ``regions`` and
    ``lines`` (heading levels, headline splits, page numbers removed). Stats: ``leveled``, ``demoted``, ``split``,
    ``drop_capitals``, ``numbers_dropped``. Its constructor is ``RuleBlock``'s (``preset``, ``transcription``,
    ``options``).

    Example:
        Typographer("ratios@1")
    """

    name = "typographer"
    step = "typography"
    docs_args = {"preset": "ratios@1"}
    parts_read = ("regions", "lines")
    parts_added = ("hierarchy",)
    parts_replaced = ("regions", "lines")      # heading levels, headline splits, page numbers removed

    def apply(self, page, t) -> None:
        self.engine(t)
        self.count(t.steps[-1].measurements, ("leveled", "demoted", "split", "drop_capitals", "numbers_dropped"))
