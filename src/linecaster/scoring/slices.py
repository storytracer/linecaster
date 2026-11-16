"""Page slices: the pages of a benchmark grouped by what their ground truth holds, so that a run's rates can be read on
the pages with tables or formulas apart from the rest (``summarize``: an evidence record's ``slices``). A page is in
every slice its ground truth meets (``SLICES``); a slice is a property of the page, never of the output scored."""
from __future__ import annotations

from ..data.transcription import Transcription

#: slice -> what puts a page in it (written into the evidence record)
SLICES = {
    "plain": "no table and no formula in the ground truth",
    "tables": "a data table in the ground truth (linecaster.scoring.tables: printed as a table, not a contents list or layout)",
    "formulas": "a formula in the ground truth (a formula region or a formula span of a line)",
}


def page_slices(gt: Transcription) -> list[str]:
    """The slices of a page with ground truth ``gt``."""
    from .tables import table_kind

    tables = [tb for tb in gt.tables if tb.cells and table_kind(tb) == "data"]     # printed as tables
    out = []
    if not tables and not gt.formulas:
        out.append("plain")
    if tables:
        out.append("tables")
    if gt.formulas:
        out.append("formulas")
    return out
