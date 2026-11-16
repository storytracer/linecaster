"""OmniDocBench's formats (opendatalab/OmniDocBench, its end-to-end evaluation), so that its own harness can score a
linecaster run against any linecaster ground truth (``linecaster.scoring.harness``):

* ``truth_page``: a ground truth's page as one entry of OmniDocBench's ground-truth JSON: its elements in reading
  order (``layout_dets``: ``category_type``, ``order``, ``anno_id``, ``ignore``, the text, a table's ``html``, a display
  formula's ``latex``) and ``page_info`` (``image_path``, the key a prediction file is found by, and
  ``page_attribute``, the groups the harness reports by). Roles map to OmniDocBench's categories (``CATEGORIES``); a
  line a formula fills (``display_formula``) is its own ``equation_isolated``, splitting its paragraph; an inline
  formula stays in the text as the ground truth writes it (``$…$``), as OmniDocBench's own ground truth has it. The
  harness reads no boxes (``poly`` is left out).
* ``prediction_markdown``: a run's page as the Markdown OmniDocBench's models write: blocks in reading order, a
  heading ``#`` at its level, a table as HTML, a formula region ``$$…$$``; furniture written as it is (the harness
  sets aside what matches the ground truth's furniture). A transcription without regions (a VLM's completion read as
  lines) is its text as the model wrote it.

Figures and what a model writes about them (descriptions) are in neither; hidden lines (``Transcription.hidden_lines``)
neither."""
from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from ..data.policy import DEFAULT_POLICY, RenderingPolicy
from ..data.refs import parse
from ..data.transcription import Table, Transcription

#: linecaster content roles -> OmniDocBench's ``category_type`` (other roles: ``text_block``)
CATEGORIES = {
    "heading": "title", "title": "title",
    "caption": "figure_caption",
    "footnote": "page_footnote", "footnote_continued": "page_footnote", "endnote": "page_footnote",
    "header": "header", "footer": "footer", "page_number": "page_number",
    "catch_word": "footer", "signature_mark": "footer",
    "table": "table", "formula": "equation_isolated", "chemistry": "equation_isolated",
    "picture": "figure", "chart": "figure", "map": "figure", "music": "figure", "advert": "figure",
}
#: roles with no text to score: never written
SKIP = {"separator", "noise"}
#: what may follow a formula on its line and still leave the line to it: punctuation, spaces, an equation number
_TAIL = re.compile(r"[\s.,;:()\[\]0-9]*")


def table_html(table: Table) -> str:
    """A table as HTML, every cell with its spans, a column header as ``th``."""
    from html import escape

    rows: dict[int, list[str]] = {}
    for c in sorted(table.cells, key=lambda c: (c.start_row, c.start_col)):
        span = "".join(f' {k}span="{n}"' for k, n in (("row", c.end_row - c.start_row), ("col", c.end_col - c.start_col))
                       if n > 1)
        tag = "th" if c.column_header else "td"
        rows.setdefault(c.start_row, []).append(f"<{tag}{span}>{escape(' '.join(c.text.split()), quote=False)}</{tag}>")
    return "<table>" + "".join(f"<tr>{''.join(r)}</tr>" for _, r in sorted(rows.items())) + "</table>"


def _blocks(t: Transcription, policy: RenderingPolicy) -> Iterator[tuple[str | None, str | None, Any]]:
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


def display_formula(t: Transcription, line_id: str, text: str) -> str | None:
    """The LaTeX of a formula that fills its line (an equation number or punctuation may follow it), else None."""
    for f in t.formulas:
        ref = parse(f.target)
        if ref.id == line_id and ref.span is not None:
            a, b = ref.span
            if not text[:a].strip() and _TAIL.fullmatch(text[b:]) and f.latex.strip():
                return f.latex.strip()
    return None


def truth_page(page_id: str, t: Transcription, policy: RenderingPolicy = DEFAULT_POLICY,
               attributes: dict[str, Any] | None = None) -> dict:
    """The ground truth ``t`` of page ``page_id`` as an entry of OmniDocBench's ground-truth JSON (module docstring);
    ``attributes`` its ``page_attribute`` (the groups the harness reports by)."""
    dets: list[dict] = []

    def add(category: str, **content) -> None:
        dets.append({"category_type": category, "order": len(dets) + 1, "anno_id": len(dets), "ignore": False,
                     **content})

    for region, role, what in _blocks(t, policy):
        if isinstance(what, Table):
            add("table", html=table_html(what), text="")
        elif not isinstance(what, list):                            # a formula region
            add("equation_isolated", latex=f"$${what.latex.strip()}$$")
        else:
            category = CATEGORIES.get(role or "", "text_block")
            if category in ("table", "equation_isolated"):          # a table or formula region read as lines only
                category = "text_block"
            run: list[str] = []
            for ln in what:
                s = t.text_of(ln) or ""
                latex = display_formula(t, ln.id, s) if category == "text_block" else None
                if latex is None:
                    run.append(s)
                    continue
                if any(x.strip() for x in run):
                    add(category, text="\n".join(run))
                run = []
                add("equation_isolated", latex=f"$${latex}$$")
            if any(x.strip() for x in run):
                add(category, text="\n".join(run))
    return {"layout_dets": dets, "extra": {"relation": []},
            "page_info": {"page_no": 0, "height": t.source.image_height or 0, "width": t.source.image_width or 0,
                          "image_path": f"{page_id}.png", "page_attribute": dict(attributes or {})}}


def prediction_markdown(t: Transcription | None, policy: RenderingPolicy = DEFAULT_POLICY) -> str:
    """A run's page ``t`` as Markdown (module docstring); an empty string for a page the run lacks."""
    if t is None:
        return ""
    if not t.regions:                                               # a completion read as lines: as the model wrote it
        return "\n".join(t.text_of(ln) or "" for ln in t.ordered_lines())
    out: list[str] = []
    for region, role, what in _blocks(t, policy):
        if isinstance(what, Table):
            out.append(table_html(what))
        elif not isinstance(what, list):
            out.append(f"$$\n{what.latex.strip()}\n$$")
        elif CATEGORIES.get(role or "") == "figure":
            continue
        else:
            text = "\n".join(t.text_of(ln) or "" for ln in what).strip()
            if not text:
                continue
            if role in ("heading", "title"):
                level = t.heading_level(region) if region else None
                text = "#" * max(1, min(level or 2, 6)) + " " + " ".join(text.split())
            out.append(text)
    return "\n\n".join(out)
