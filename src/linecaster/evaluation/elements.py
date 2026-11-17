"""The elements a page is compared by (``linecaster.evaluation.matching``): the units of a page's content, the same rule on
both sides of a comparison. An element is

* ``text``: a run of consecutive lines of one region in reading order (a paragraph, a heading, a note, a running
  head), its lines joined by line breaks, illegible spans as U+FFFD (``render.line_text``); a line a display formula
  fills (``display_formula``) is a ``formula`` element of its own, splitting its region's text;
* ``table``: a region's table with cells, compared by its cell text (``table_text``: rows of cells) and its structure
  (``linecaster.evaluation.teds``); with ``tables="data"`` only a data table (``linecaster.evaluation.tables``) is a
  table, a contents list or a layout table is its text;
* ``formula``: a formula region's LaTeX (``Formula`` of the region) or a display formula's;
* ``description``: what an annotator wrote about a zone (a picture's description) where the policy puts it in a
  scored layer (``RenderingPolicy.described``; ``page-layers-described``), after its region's elements (a picture
  without lines in its place in the regions' order).

A transcription without regions (a model's completion read as lines) has each non-empty line as an element, except
what Markdown or HTML spans over lines: a ``<table>…</table>`` or a run of pipe-table rows is a ``table`` element, a
``$$…$$`` or ``\\[…\\]`` block a ``formula`` element, a ``#`` line a ``text`` element with the role ``heading``. A
region whose whole text is an HTML table and that has no ``Table`` is read the same way. Granularity is never
reconciled here: matching does that.

Roles are resolved with the policy's precedence, layers with ``policy.layer_of``; regions and lines a policy puts in
``none`` or ``metadata``, and separators and noise, are no elements. Each element records the writing system that
holds for it (``language``, ``script``, ``direction``: recorded values only, resolved through what encloses it,
``Transcription.written``) and its region's other classifications, for reporting by strata.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from linecaster.data.policy import DEFAULT_POLICY, RenderingPolicy
from linecaster.data.refs import parse
from linecaster.data.transcription import Table, Transcription

#: the version of the element scorer's rules (elements, matching, attribution), in evidence records: a change that
#: moves element scores raises it
ELEMENTS_VERSION = 1
#: roles with no text to compare: never elements
SKIP = {"separator", "noise"}
#: layers whose content is never compared
UNSCORED = {"none", "metadata"}
#: what may follow a formula on its line and still leave the line to it: punctuation, spaces, an equation number
_TAIL = re.compile(r"[\s.,;:()\[\]0-9]*")
_PIPE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_PIPE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
#: writing-system schemes an element records (``Transcription.written``)
WRITING = ("language", "script", "direction")


@dataclass(frozen=True)
class Element:
    """One unit of a page's content (module docstring).

    Args:
        index: its place in the side's reading order (0, 1, ...).
        kind: ``text``, ``table`` or ``formula``.
        role: its content role (``None`` without one).
        layer: its layer under the policy (``body``, ``furniture``, ``notes``, ...).
        content: what is compared: the text; a table's cell text (``table_text``); a formula's LaTeX.
        region: the region it comes from (``None``: lines without a region).
        lines: the ids of its lines.
        table: its table (``table`` elements).
        latex: its LaTeX (``formula`` elements).
        table_kind: a table's kind (``linecaster.evaluation.tables``), also for a table compared as text.
        attributes: ``(scheme, value)`` pairs that hold for it: the writing system and its region's classifications.
    """

    index: int
    kind: str
    role: str | None
    layer: str
    content: str
    region: str | None = None
    lines: tuple[str, ...] = ()
    table: Table | None = None
    latex: str | None = None
    table_kind: str | None = None
    attributes: tuple[tuple[str, str], ...] = field(default=())


def table_text(table: Table) -> str:
    """A table's text as lines: each row's cells in order, separated by spaces (a table not scored as a table)."""
    rows: dict[int, list] = {}
    for c in sorted(table.cells, key=lambda c: (c.start_row, c.start_col)):
        if (c.text or "").strip():
            rows.setdefault(c.start_row, []).append(" ".join(c.text.split()))
    return "\n".join(" ".join(r) for _, r in sorted(rows.items()))


def display_formula(t: Transcription, line_id: str, text: str) -> str | None:
    """The LaTeX of a formula that fills its line (an equation number or punctuation may follow it), else None."""
    for f in t.formulas:
        ref = parse(f.target)
        if ref.id == line_id and ref.span is not None:
            a, b = ref.span
            if not text[:a].strip() and _TAIL.fullmatch(text[b:]) and f.latex.strip():
                return f.latex.strip()
    return None


def reading_blocks(t: Transcription, policy: RenderingPolicy) -> Iterator[tuple[str | None, str | None, Any]]:
    """The page in reading order as (region, role, what): a region's ``Table``, its ``Formula`` (a formula region),
    or the list of its lines; a table or formula region without lines in its place in the regions' order."""
    tables = {tb.target: tb for tb in t.tables if tb.cells}
    roles = {r.id: t.role(r.id) for r in t.regions}
    formulas = {f.target: f for f in t.formulas if f.target in roles and f.latex.strip()}
    rank = t.region_ranks()
    with_lines = {t.region_of(ln) for ln in t.lines}
    pending = [r.id for r in sorted(t.regions, key=lambda r: rank.get(r.id, len(rank)))
               if (r.id in tables or r.id in formulas) and r.id not in with_lines]
    done: set[str] = set()
    current: tuple[str | None, list] | None = None

    def whole(region):
        return region, roles.get(region), tables.get(region) or formulas[region]

    for ln in t.ordered_lines():
        region = t.region_of(ln)
        while pending and rank.get(pending[0], len(rank)) < rank.get(region, len(rank)):
            if current:
                yield current[0], roles.get(current[0]), current[1]
                current = None
            yield whole(pending.pop(0))
        if roles.get(region) in SKIP or (region is not None and policy.layer_of(t, region) == "none"):
            continue
        if region in tables or region in formulas:
            if region not in done:
                if current:
                    yield current[0], roles.get(current[0]), current[1]
                    current = None
                done.add(region)
                yield whole(region)
            continue
        if current is None or current[0] != region:
            if current:
                yield current[0], roles.get(current[0]), current[1]
            current = (region, [])
        current[1].append(ln)
    if current:
        yield current[0], roles.get(current[0]), current[1]
    for region in pending:
        yield whole(region)


def _attributes(t: Transcription, target: str, region: str | None) -> tuple[tuple[str, str], ...]:
    out = []
    for scheme in WRITING:
        value = getattr(t, scheme)(target) if hasattr(t, scheme) else None
        if value:
            out.append((scheme, str(value)))
    if region is not None:
        seen = {s for s, _ in out} | {"role", "status", "heading_level"}
        for c in t.classifications:
            if c.target == region and c.scheme not in seen:
                out.append((c.scheme, str(c.value)))
                seen.add(c.scheme)
    return tuple(out)


def _parsed_table(html: str) -> Table | None:
    from linecaster.formats.html_table import table_from_html

    try:
        return table_from_html(html, annotator=0, target="")
    except Exception:  # noqa: BLE001 - not a table after all: the text stays text
        return None


def _pipe_table(rows: list[str]) -> Table | None:
    from linecaster.data.transcription import Cell

    body = [r for r in rows if not _PIPE_RULE.match(r)]
    cells = []
    for i, row in enumerate(body):
        parts = [p.strip() for p in row.strip().strip("|").split("|")]
        for j, p in enumerate(parts):
            cells.append(Cell(start_row=i, end_row=i + 1, start_col=j, end_col=j + 1, text=p,
                              column_header=i == 0 and len(body) != len(rows)))
    if not cells:
        return None
    return Table(annotator=0, target="", num_rows=len(body), num_cols=max(c.end_col for c in cells), cells=cells)


class _Builder:
    def __init__(self, t: Transcription, policy: RenderingPolicy, tables: str):
        self.t, self.policy, self.tables = t, policy, tables
        self.out: list[Element] = []

    def add(self, kind: str, content: str, role: str | None, layer: str, region: str | None,
            lines: tuple[str, ...] = (), **fields) -> None:
        if not content.strip() and kind != "table":
            return
        target = lines[0] if lines else (region or "")
        self.out.append(Element(len(self.out), kind, role, layer, content, region, lines,
                                attributes=_attributes(self.t, target, region), **fields))

    def table(self, tb: Table, role: str | None, layer: str, region: str | None, lines: tuple[str, ...] = ()) -> None:
        from linecaster.evaluation.tables import table_kind

        kind = table_kind(tb)
        if self.tables == "all" or kind == "data":
            self.add("table", table_text(tb), role or "table", layer, region, lines, table=tb, table_kind=kind)
        else:
            self.add("text", table_text(tb), role, layer, region, lines, table_kind=kind)

    def text_run(self, text: str, role: str | None, layer: str, region: str | None, lines: tuple[str, ...]) -> None:
        stripped = text.strip()
        if stripped.lower().startswith("<table") and stripped.lower().endswith("</table>"):
            tb = _parsed_table(stripped)
            if tb is not None:
                self.table(tb, role, layer, region, lines)
                return
        self.add("text", text, role, layer, region, lines)


def elements(t: Transcription | None, policy: RenderingPolicy = DEFAULT_POLICY, tables: str = "data") -> list[Element]:
    """The elements of ``t`` in reading order (module docstring); none for a missing transcription."""
    if t is None:
        return []
    from linecaster.evaluation.render import illegible_spans

    b = _Builder(t, policy, tables)
    illegible = illegible_spans(t)
    described = {r: [(lr, x) for lr, x in ds if lr not in UNSCORED] for r, ds in policy.described(t).items()}
    rank = t.region_ranks()
    blocks = list(reading_blocks(t, policy)) if t.regions else []
    yielded = {region for region, _, _ in blocks}
    loose = sorted((r for r in described if r is not None and r not in yielded), key=lambda r: rank.get(r, len(rank)))

    def describe(region: str | None) -> None:
        for layer, content in described.pop(region, ()):
            b.add("description", content, t.role(region) if region else None, layer, region)

    def before(r: float) -> None:
        while loose and rank.get(loose[0], len(rank)) < r:
            describe(loose.pop(0))

    if not t.regions:
        _line_elements(b, t, illegible, policy)
    for region, role, what in blocks:
        before(rank.get(region, len(rank)))
        _block(b, t, illegible, policy, region, role, what)
        describe(region)
    before(float("inf"))
    for region in list(described):                  # the page's, and those of regions the order leaves out
        describe(region)
    return b.out


def _block(b: _Builder, t: Transcription, illegible, policy: RenderingPolicy, region: str | None, role: str | None,
           what) -> None:
    """One of ``reading_blocks``' blocks as its elements."""
    from linecaster.evaluation.render import line_text

    layer = policy.layer_of(t, region) if region is not None else policy.layer(None)
    if layer in UNSCORED or role in SKIP:
        return
    if isinstance(what, Table):
        b.table(what, role, layer, region)
    elif not isinstance(what, list):
        b.add("formula", what.latex.strip(), role or "formula", layer, region, latex=what.latex.strip())
    else:
        run: list = []

        def flush() -> None:
            if run:
                text = "\n".join(x for _, x in run)
                b.text_run(text, role, layer, region, tuple(ln.id for ln, _ in run))
                run.clear()

        for ln in what:
            x = line_text(t, ln, illegible)
            if x is None:
                continue
            latex = display_formula(t, ln.id, x)
            if latex is not None:
                flush()
                b.add("formula", latex, "formula", layer, region, (ln.id,), latex=latex)
                continue
            run.append((ln, x))
        flush()


def _line_elements(b: _Builder, t: Transcription, illegible, policy: RenderingPolicy) -> None:
    """A transcription without regions: its lines, with Markdown's and HTML's blocks that span lines (module
    docstring)."""
    from linecaster.evaluation.render import line_text

    layer = policy.layer(None)
    lines = [(ln, line_text(t, ln, illegible)) for ln in t.ordered_lines()]
    lines = [(ln, s) for ln, s in lines if s is not None]
    k = 0
    while k < len(lines):
        ln, s = lines[k]
        stripped = s.strip()
        if not stripped:
            k += 1
            continue
        if stripped.lower().startswith("<table"):                     # an HTML table, over lines to its end
            j = k
            while j < len(lines) and "</table>" not in lines[j][1].lower():
                j += 1
            j = min(j, len(lines) - 1)
            html = "\n".join(x for _, x in lines[k:j + 1])
            ids = tuple(x.id for x, _ in lines[k:j + 1])
            tb = _parsed_table(html)
            if tb is not None:
                b.table(tb, "table", layer, None, ids)
            else:
                b.add("text", html, None, layer, None, ids)
            k = j + 1
            continue
        if _PIPE_ROW.match(s):                                          # a pipe table: its run of rows
            j = k
            while j + 1 < len(lines) and _PIPE_ROW.match(lines[j + 1][1]):
                j += 1
            if j > k:
                tb = _pipe_table([x for _, x in lines[k:j + 1]])
                ids = tuple(x.id for x, _ in lines[k:j + 1])
                if tb is not None:
                    b.table(tb, "table", layer, None, ids)
                    k = j + 1
                    continue
        for opening, closing in (("$$", "$$"), ("\\[", "\\]")):        # a display formula block
            if stripped.startswith(opening):
                body = stripped[len(opening):]
                j = k
                if not (body.rstrip().endswith(closing) and len(body.strip()) >= len(closing)):
                    j = k + 1
                    while j < len(lines) and closing not in lines[j][1]:
                        j += 1
                    j = min(j, len(lines) - 1)
                latex = "\n".join(x for _, x in lines[k:j + 1]).strip()
                latex = latex[len(opening):]
                latex = latex[:latex.rfind(closing)] if closing in latex else latex
                b.add("formula", latex.strip(), "formula", layer, None, tuple(x.id for x, _ in lines[k:j + 1]),
                      latex=latex.strip())
                k = j + 1
                break
        else:
            m = _HEADING.match(s)
            if m:
                b.add("text", m.group(2), "heading", layer, None, (ln.id,))
            else:
                b.text_run(s, None, layer, None, (ln.id,))
            k += 1


__all__ = ["Element", "SKIP", "UNSCORED", "display_formula", "elements", "reading_blocks", "table_text"]
