"""A table a model writes as HTML (``<table><tr><td>…``), read into a ``Table``: its cells placed on the grid with their
row and column spans (a cell goes to the first column its row leaves free), ``th`` a column header, each cell's text
its text content with whitespace runs as one space (``<br>`` a space). The HTML is kept as the model wrote it
(``Table.html``). Nested tables are read as text of their cell."""
from __future__ import annotations

from linecaster.data.transcription import Cell, Table


def _span(value: str | None) -> int:
    try:
        return max(1, int(str(value).strip()))
    except (TypeError, ValueError):
        return 1


def table_from_html(html: str, annotator: int, target: str, output: int | None = None) -> Table | None:
    """The first ``<table>`` in ``html`` as a ``Table`` of region ``target`` by ``annotator`` (from raw output
    ``output``); None when ``html`` holds no table with a cell."""
    from lxml import html as H

    try:
        root = H.fromstring(f"<div>{html}</div>")
    except Exception:  # noqa: BLE001 - lxml refuses an empty or broken document
        return None
    table = next(iter(root.iter("table")), None)
    if table is None:
        return None
    rows = [tr for tr in table.iter("tr") if next((p for p in tr.iterancestors("table")), None) is table]
    taken: set[tuple[int, int]] = set()
    cells: list[Cell] = []
    for r, tr in enumerate(rows):
        c = 0
        for td in tr:
            if td.tag not in ("td", "th"):
                continue
            while (r, c) in taken:
                c += 1
            rs, cs = _span(td.get("rowspan")), _span(td.get("colspan"))
            taken.update((r + i, c + j) for i in range(rs) for j in range(cs))
            for br in td.iter("br"):
                br.tail = " " + (br.tail or "")
            cells.append(Cell(start_row=r, end_row=r + rs, start_col=c, end_col=c + cs,
                              text=" ".join(td.text_content().split()), column_header=td.tag == "th"))
            c += cs
    if not cells:
        return None
    return Table(annotator=annotator, output=output, target=target, num_rows=max(x.end_row for x in cells),
                 num_cols=max(x.end_col for x in cells), cells=cells, html=html)
