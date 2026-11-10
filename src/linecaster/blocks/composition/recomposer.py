"""``Recomposer``: running text from the rows of a page's (or an item's pages') text regions, the transcription's
``paragraphs`` (``recomposition.*`` engines; ``recomposition.unicode.v1`` runs ``linecaster.text.recomposition``)."""
from __future__ import annotations

from typing import Any

from ...errors import PipelineConfigError
from ..base.contract import Contract, parts
from ..base.item import item_pages, set_item_pages
from ..base.rule import RuleBlock, now, stamp

UNITS = ("page", "item")
#: the recomposition's measurements the block counts
COUNTED = ("paragraphs", "continuations", "marks_removed", "marks_kept")


class Recomposer(RuleBlock):
    """Recomposes the running text of a page or an item into paragraphs by a recomposition engine.

    The rows of each text region become ``paragraphs``, each with its decisions; paragraphs that already exist are
    made anew. Reads ``regions`` and ``lines``; adds ``paragraphs`` and declares them replaced (an item-level
    recomposition after a page-level one). Stats: ``paragraphs``, ``continuations``, ``marks_removed``,
    ``marks_kept`` (and ``items``).

    ``unit="page"``: each page by itself (a paragraph continues into the next text region of the page).
    ``unit="item"``: the pages of an item record together, in order (``linecaster.blocks.base.item``): the lexicon
    grows page by page, and a paragraph open at the foot of a page continues on the next one.

    Args:
        preset: the recomposition engine: a preset (e.g. ``unicode-recomposition@1``) or an ``InProcess`` engine
            spec.
        transcription: the transcription to recompose.
        unit: ``page`` (a stream of pages) or ``item`` (a stream of item records, after a ``Binder``).
        options: engine options over the preset's; ``None``: the preset's.

    Example:
        Recomposer("unicode-recomposition@1", unit="item")
    """

    name = "recomposer"
    step = "recomposition"
    docs_args = {"preset": "unicode-recomposition@1"}

    def __init__(self, preset, transcription: str = "ocr_new", unit: str = "page",
                 options: dict[str, Any] | None = None):
        if unit not in UNITS:
            raise PipelineConfigError(f"recomposer: unit {unit!r}; choose {', '.join(UNITS)}")
        self.unit = unit
        super().__init__(preset, transcription, options)

    def contract(self) -> Contract:
        """It reads the regions and lines and adds the paragraphs; it makes them anew where they exist (an item-level
        recomposition after a page-level one), so it declares them replaced too."""
        reads, adds = parts(("regions", "lines"), self.transcription), parts(("paragraphs",), self.transcription)
        return Contract(unit=self.unit, role=self.role, reads=reads, adds=adds, replaces=adds)

    def apply(self, page, t) -> None:
        self.engine([t], page_ids=[page.page_id])
        self.count(t.steps[-1].measurements, COUNTED)

    def run(self, data, rank: int = 0, world_size: int = 1):
        if self.unit == "page":
            yield from super().run(data, rank, world_size)
            return
        for doc in data:
            self.stat_update("items")
            with self.track_time():
                pages = item_pages(doc)
                ts = [p.transcription(self.transcription) for p in pages]
                start, began = now()
                n = [len(t.steps) for t in ts]
                self.engine(ts, page_ids=[p.page_id for p in pages])
                for t, k in zip(ts, n):
                    for info in t.steps[k:]:
                        stamp(info, self.backend, start, began)
                    self.count(t.steps[-1].measurements, COUNTED)
                set_item_pages(doc, pages)
            yield doc
