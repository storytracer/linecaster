"""``HierarchyDetector``: the typographic hierarchy of a page (``typography.*`` engines; ``hierarchy.ratios.v1``:
heading levels from type-size ratios, ``linecaster.text.hierarchy``)."""
from __future__ import annotations

from linecaster.core.rule import RuleComponent


class HierarchyDetector(RuleComponent):
    """Determines the typographic hierarchy of every page by a typography engine.

    Heading levels from type size, headline splits, drop capitals, uncertain page numbers removed (see
    ``linecaster.text.hierarchy``), each an annotation by the engine's annotator: roles and heading levels, a
    headline region with its lines linked to it, a drop capital joined to its line, ``status`` ``removed``, a new
    reading order. Reads ``regions`` and ``lines``; adds ``hierarchy``; replaces ``regions`` and ``lines`` (what
    they are and how they are read). Stats: ``leveled``, ``demoted``, ``split``, ``drop_capitals``,
    ``numbers_dropped``. Its constructor is ``RuleComponent``'s (``preset``, ``transcription``, ``options``).

    Example:
        HierarchyDetector("ratios")
    """

    name = "hierarchy"
    step = "hierarchy"
    docs_args = {"preset": "ratios"}
    parts_read = ("regions", "lines")
    parts_added = ("hierarchy",)
    parts_replaced = ("regions", "lines")      # roles, heading levels, headline splits, removals, reading order

    def apply(self, page, t) -> None:
        self.engine(t)
        self.count(t.annotators[-1].measurements, ("leveled", "demoted", "split", "drop_capitals", "numbers_dropped"))
