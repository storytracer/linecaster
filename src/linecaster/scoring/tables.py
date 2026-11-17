"""What kind of table a ground truth's table is, from the table alone: ``data`` (a table printed as one: at least two
rows and two columns of cells, whatever they hold, text or numbers), ``contents`` (a list of entries with their page
numbers laid out as a table: a table of contents, an index, a list of illustrations) or ``layout`` (table markup that
arranges a page: one row, one column or one cell; a brace grouping lines). A source like Wikisource lays out far more
than it tabulates (on English Wikisource's ground truth, 2026-11-16: 16,005 of 21,418 tables have one row, one column
or one cell), so a table metric is meaningful only on its ``data`` tables (``linecaster.formats.omnidocbench``, the
page slices). The kind is computed, never stored: the ground truth keeps every table as it is.

``contents``: at least three rows; in at least 60 % of the rows with an entry the last cell is a reference (a page,
chapter or section number, in any script's digits or roman, with or without ``p.``, ``pp.``, ``page``, ``cap.``,
``ch.``, ``§``, …, any abbreviation of up to four letters (``S.``, ``стр.``) or ``第…頁``, one or a list or range of
them: ``45, 172``, ``12–15``) and the first cell has letters; and either the references do not go
down in at least 70 % of the steps from row to row (a table of contents), or the entries do not (an index, in
alphabetical order). A table of contents' entries are titles (a median of three words or more: runs between spaces, or
in a script without spaces Unicode's words, a character each); an index's entries have two words or more and the index is long (15 entries or more) or a fifth of its entries have several references.
A column of counts, amounts or years with short labels rarely meets either, so a data table whose last column holds
numbers stays a data table. ``layout``: one row, one column or one cell, or fewer than two rows, or under a third of
them, with two filled cells (a table that is one column in practice); or a table of at most six rows with a cell that
holds only brackets and braces (``}``, ``⎫``), a brace grouping lines."""
from __future__ import annotations

import re

from linecaster.data.transcription import Table

#: a reference as a contents page or index prints it: a page, chapter or section, in the digits of any script or roman
#: (``j`` for ``i``), with or without its word (one of these, or any abbreviation of up to four letters with its
#: period: ``S. 12``, ``стр. 5``, ``pág. 3``; ``第12頁``, ``12页``); one, or a list or range (only the first counts)
_REF = r"(?:\d{1,4}|[ivxlcdmj]{1,8})"
REFERENCE = re.compile(r"^\s*(?:(?:p|pp|page|pages|cap|ca|ch|chap|chapter|sect|sec|art|no|§|pl|plate|fig)\.?\s*"
                       r"|[^\W\d_]{1,4}\.\s*|第\s*)?"
                       rf"({_REF})\.?((?:\s*[,–—-]\s*{_REF}\.?)*)\s*[頁页章節节回]?\s*$", re.I)
#: a cell that holds only brackets and braces: a brace grouping lines
BRACE = re.compile(r"^[\s{}()\[\]⎫⎬⎭⎧⎨⎩⎪]+$")
_LETTER = re.compile(r"[^\W\d_]")
_ROMAN = {"i": 1, "j": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def _number(s: str) -> int | None:
    m = REFERENCE.match(s)
    if not m:
        return None
    v = m.group(1).lower()
    if v.isdigit():
        return int(v)
    total = 0
    for a, b in zip(v, v[1:] + " "):
        x = _ROMAN.get(a, 0)
        total += -x if _ROMAN.get(b, 0) > x else x
    return total


def _rising(xs: list) -> bool:
    steps = list(zip(xs, xs[1:]))
    return bool(steps) and sum(b >= a for a, b in steps) >= 0.7 * len(steps)


def _rows(table: Table) -> list[list[str]]:
    rows: dict[int, list[tuple[int, str]]] = {}
    for c in table.cells:
        rows.setdefault(c.start_row, []).append((c.start_col, " ".join((c.text or "").split())))
    return [[t for _, t in sorted(r)] for _, r in sorted(rows.items())]


def _words(text: str) -> int:
    """An entry's words: its runs between spaces, or, in a script written without spaces (Chinese, Japanese, Thai: one
    run), Unicode's words (``linecaster.scoring.tokens``, ``uax29``: a character each)."""
    runs = text.split()
    if len(runs) > 1:
        return len(runs)
    from linecaster.scoring.tokens import tokens

    return max(len(runs), len(tokens(text, "uax29")))


def is_contents(table: Table) -> bool:
    """Whether ``table`` is a list of entries with references: a table of contents or an index (module docstring)."""
    rows = [[t for t in r if t] for r in _rows(table)]
    rows = [r for r in rows if r]
    if len(rows) < 3:
        return False
    entries = [r for r in rows if len(r) >= 2]
    numbered = [r for r in entries if _number(r[-1]) is not None and _LETTER.search(r[0])]
    if len(numbered) < 3 or len(numbered) < 0.6 * max(len(entries), 1):
        return False
    words = sorted(_words(" ".join(r[:-1])) for r in numbered)[len(numbered) // 2]    # the median entry's words
    if _rising([_number(r[-1]) for r in numbered]) and words >= 3:          # a table of contents: titles, pages rising
        return True
    several = sum(1 for r in numbered if REFERENCE.match(r[-1]).group(2).strip())
    return (_rising([r[0].casefold() for r in numbered]) and words >= 2      # an index: entries in alphabetical order,
            and (len(numbered) >= 15 or several >= 0.2 * len(numbered)))    # long, or with several references


def table_kind(table: Table) -> str:
    """``data``, ``contents`` or ``layout`` (module docstring)."""
    if len(table.cells) <= 1 or table.num_rows <= 1 or table.num_cols <= 1:
        return "layout"
    wide = sum(1 for r in _rows(table) if sum(1 for t in r if t) >= 2)
    if wide < 2 or wide < table.num_rows / 3:              # one column in practice
        return "layout"
    if table.num_rows <= 6 and any(BRACE.fullmatch((c.text or "").strip()) for c in table.cells if (c.text or "").strip()):
        return "layout"
    if is_contents(table):
        return "contents"
    return "data"
