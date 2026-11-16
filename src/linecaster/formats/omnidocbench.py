"""OmniDocBench's formats (opendatalab/OmniDocBench, its end-to-end evaluation), so that its own evaluation, run by
whoever exports, scores a linecaster run against any linecaster ground truth (``export``, ``linecaster export
omnidocbench``); linecaster runs none of OmniDocBench's code:

* ``truth_page``: a ground truth's page as one entry of OmniDocBench's ground-truth JSON: its elements in reading
  order (``layout_dets``: ``category_type``, ``order``, ``anno_id``, ``ignore``, the text, a table's ``html``, a display
  formula's ``latex``) and ``page_info`` (``image_path``, the key a prediction file is found by, and
  ``page_attribute``, the groups the harness reports by). Roles map to OmniDocBench's categories (``CATEGORIES``); a
  line a formula fills (``display_formula``) is its own ``equation_isolated``, splitting its paragraph; an inline
  formula stays in the text as the ground truth writes it (``$…$``), as OmniDocBench's own ground truth has it. The
  harness reads no boxes (``poly`` is left out). Only the ground truth's data tables are tables to the harness
  (``tables="data"``, ``linecaster.scoring.tables``): a contents list or a layout table is its text.
* ``prediction_markdown``: a run's page as the Markdown OmniDocBench's models write: blocks in reading order, a
  heading ``#`` at its level, a table as HTML, a formula region ``$$…$$`` and so a line a formula fills (as in
  ``truth_page``: the same rule on both sides); furniture written as it is (the harness
  sets aside what matches the ground truth's furniture). A transcription without regions (a VLM's completion read as
  lines) is its text as the model wrote it. Its tables follow the same rule as the ground truth's: with
  ``tables="data"`` a contents list or layout table is its text.
* ``export``: a folder OmniDocBench's evaluation reads: ``truth.json``, ``predictions/<page id>.md`` (a page the run
  lacks or failed on: an empty prediction), ``export.yaml`` (what was exported, with what) and a ``README.md`` naming
  OmniDocBench's own command. A ``strategy`` (``nfc``, say) is applied to every text of both sides alike.

Figures and what a model writes about them (descriptions) are in neither; hidden lines (``Transcription.hidden_lines``)
neither.

What OmniDocBench's evaluation (at 7ddb8df) measures, so that its results are read rightly: its text score keeps
only ``\w`` characters and CJK ideographs, so combining marks (Devanagari vowel signs, Arabic vowel marks, Hebrew
points, Thai vowels), punctuation and spaces are not compared, and nothing is put in NFC (``nfc`` as the export's
``strategy`` makes both sides alike); predicted text that matches no ground-truth element, and predicted tables that
match no ground-truth table, are not counted; captions and footnotes are matched but not scored; its "overall" needs
its formula metric CDM (TeX Live) and pages with tables and formulas. It runs on Python before 3.12, in an
environment of its own. linecaster's own scorer (``linecaster.scoring``) is the measure for scripts with marks."""
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


def display_formula(t: Transcription, line_id: str, text: str) -> str | None:
    """The LaTeX of a formula that fills its line (an equation number or punctuation may follow it), else None."""
    for f in t.formulas:
        ref = parse(f.target)
        if ref.id == line_id and ref.span is not None:
            a, b = ref.span
            if not text[:a].strip() and _TAIL.fullmatch(text[b:]) and f.latex.strip():
                return f.latex.strip()
    return None


def table_text(table: Table) -> str:
    """A table's text as lines: each row's cells in order, separated by spaces (a table not scored as a table)."""
    rows: dict[int, list] = {}
    for c in sorted(table.cells, key=lambda c: (c.start_row, c.start_col)):
        if (c.text or "").strip():
            rows.setdefault(c.start_row, []).append(" ".join(c.text.split()))
    return "\n".join(" ".join(r) for _, r in sorted(rows.items()))


def truth_page(page_id: str, t: Transcription, policy: RenderingPolicy = DEFAULT_POLICY,
               attributes: dict[str, Any] | None = None, tables: str = "data") -> dict:
    """The ground truth ``t`` of page ``page_id`` as an entry of OmniDocBench's ground-truth JSON (module docstring);
    ``attributes`` its ``page_attribute`` (the groups the harness reports by). ``tables``: which of its tables are
    tables to the harness: ``data`` (``linecaster.scoring.tables.table_kind``: printed as tables; a contents list
    or layout table is its text, ``text_block``, so its words are still scored) or ``all``."""
    from ..scoring.tables import table_kind

    dets: list[dict] = []

    def add(category: str, **content) -> None:
        dets.append({"category_type": category, "order": len(dets) + 1, "anno_id": len(dets), "ignore": False,
                     **content})

    for region, role, what in reading_blocks(t, policy):
        if isinstance(what, Table):
            if tables == "all" or table_kind(what) == "data":
                add("table", html=table_html(what), text="")
            elif table_text(what).strip():
                add("text_block", text=table_text(what))
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


def prediction_markdown(t: Transcription | None, policy: RenderingPolicy = DEFAULT_POLICY, tables: str = "data") -> str:
    """A run's page ``t`` as Markdown (module docstring); an empty string for a page the run lacks. ``tables``: as
    ``truth_page``'s, so that both sides write a table alike."""
    from ..scoring.tables import table_kind

    if t is None:
        return ""
    if not t.regions:                                               # a completion read as lines: as the model wrote it
        return "\n".join(t.text_of(ln) or "" for ln in t.ordered_lines())
    out: list[str] = []
    for region, role, what in reading_blocks(t, policy):
        if isinstance(what, Table):
            if tables == "all" or table_kind(what) == "data":
                out.append(table_html(what))
            elif table_text(what).strip():
                out.append(table_text(what))
        elif not isinstance(what, list):
            out.append(f"$$\n{what.latex.strip()}\n$$")
        elif CATEGORIES.get(role or "") == "figure":
            continue
        elif role in ("heading", "title"):
            text = " ".join("\n".join(t.text_of(ln) or "" for ln in what).split())
            if text:
                level = t.heading_level(region) if region else None
                out.append("#" * max(1, min(level or 2, 6)) + " " + text)
        else:
            run: list[str] = []                     # a line a formula fills is a display formula, as in truth_page
            for ln in what:
                s = t.text_of(ln) or ""
                latex = display_formula(t, ln.id, s)
                if latex is None:
                    run.append(s)
                    continue
                if "\n".join(run).strip():
                    out.append("\n".join(run).strip())
                run = []
                out.append(f"$$\n{latex}\n$$")
            if "\n".join(run).strip():
                out.append("\n".join(run).strip())
    return "\n\n".join(out)


def page_attributes(gt: Transcription) -> dict[str, str]:
    """A ground-truth page's slices (``linecaster.scoring.slices``) as OmniDocBench page attributes (``yes``/``no``),
    by which its evaluation groups its page results."""
    from ..scoring.slices import page_slices

    sl = page_slices(gt)
    return {k: "yes" if k in sl else "no" for k in ("tables", "formulas")}


README = """# An export for OmniDocBench's evaluation

Written by linecaster ({producer}); what it holds is in `export.yaml`. OmniDocBench (opendatalab/OmniDocBench) scores
it with its own code: in a checkout of OmniDocBench, with its environment (Python before 3.12), point its end-to-end
config (`configs/end2end.yaml`) at this folder, `ground_truth.data_path: {folder}/truth.json` and
`prediction.data_path: {folder}/predictions`, and run `python pdf_validation.py --config configs/end2end.yaml`.

Its text score compares only letters, digits and CJK ideographs: combining marks, punctuation and spaces are not
compared; extra predicted text and unmatched predicted tables are not counted. linecaster's own scorer is the measure
for scripts with combining marks.
"""


def export(folder, truth_rows: dict[str, dict], run_rows: dict[str, dict | None], transcription: str = "ocr_new",
           truth_transcription: str = "ground_truth", tables: str = "data", strategy: str | None = None,
           policy: RenderingPolicy = DEFAULT_POLICY) -> dict:
    """``truth_rows`` (page records by id) and the run's rows of the same pages (``run_rows``; a page without a row, or
    with errors, an empty prediction) as a folder OmniDocBench's evaluation reads (module docstring). ``strategy``: an
    output strategy (``nfc``) applied to every text of both sides. Returns the counts written to ``export.yaml``."""
    import datetime as dt
    import json
    from pathlib import Path

    import yaml

    from ..data import Page
    from ..data.transcription import producer
    from ..data.upgrade import upgrade

    write = (lambda s: s) if not strategy else _written(strategy)
    folder = Path(folder)
    (folder / "predictions").mkdir(parents=True, exist_ok=True)
    pages, missing, failed = [], 0, 0
    for pid, row in truth_rows.items():
        gt = Page.model_validate(upgrade(row)["page"]).transcriptions[truth_transcription]
        page = truth_page(pid, gt, policy, attributes=page_attributes(gt), tables=tables)
        for det in page["layout_dets"]:
            for key in ("text", "html", "latex"):
                if det.get(key):
                    det[key] = write(det[key])
        pages.append(page)
        out_row = run_rows.get(pid)
        t = None
        if out_row is not None and not out_row.get("errors"):
            t = Page.model_validate(upgrade(out_row)["page"]).transcriptions.get(transcription)
        missing += out_row is None
        failed += out_row is not None and bool(out_row.get("errors"))
        (folder / "predictions" / f"{pid}.md").write_text(write(prediction_markdown(t, policy, tables)),
                                                          encoding="utf-8")
    (folder / "truth.json").write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    counts = {"pages": len(pages), "missing": missing, "failed": failed}
    record = {"schema": "linecaster.omnidocbench-export/1", "producer": producer(), "date": dt.date.today().isoformat(),
              "transcription": transcription, "truth_transcription": truth_transcription, "tables": tables,
              "strategy": strategy or "literal", "policy": policy.ref, "counts": counts}
    (folder / "export.yaml").write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (folder / "README.md").write_text(README.format(producer=producer(), folder=folder.resolve()), encoding="utf-8")
    return counts


def _written(strategy: str):
    from ..catalog.registry import catalog

    return catalog().strategy(strategy, use="output").text
