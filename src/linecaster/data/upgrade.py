"""The upgrade of stored page records from ``linecaster.page/2`` to ``linecaster.page/3``.

``page_2_to_3(row)`` takes a stored row (``{"schema", "id", "text", "page", ...}``) and returns it in page/3.
Everything page/2 held is kept: what has a place in page/3 goes there (``docs/reference/data-model.md``, "From
``linecaster.page/2``"), the rest as extension fields ``page2__<key>``. What page/2 had already lost (text before the
unicode step, labels before typography) cannot come back. Upgrading a page/3 row changes nothing.
"""
from __future__ import annotations

from typing import Any

from .policy import role_of_label
from .transcription import (
    RULE_STEPS, SCHEMA, Annotator, Cell, Classification, Decision, Description, Edit, Formula, Line, Link, Paragraph,
    ParagraphRow, RawOutput, Reading, ReadingOrder, Region, Source, Table, Transcription, Word,
)

OLD = "linecaster.page/2"


def _ext(extra: dict | None, skip=()) -> dict[str, Any]:
    return {f"page2__{k}": v for k, v in (extra or {}).items() if k not in skip}


def _id(value: str) -> str:
    """A page/2 id as a page/3 id: ``#``, ``/`` and ``[`` (which references use) become ``_``."""
    for c in "#/[":
        value = value.replace(c, "_")
    return value


class _Steps:
    """The annotators of an upgraded set, and which made what."""

    def __init__(self, steps: list[dict], source: dict):
        self.annotators = []
        for st in steps:
            st = dict(st)
            kind = "rule" if st.get("step") in RULE_STEPS else "model"
            self.annotators.append(Annotator(kind=kind, **st))
        if not self.annotators:
            self.annotators.append(Annotator(kind="file", step="transcription",
                                             name=source.get("format") or source.get("kind") or "unknown"))

    def of(self, *steps: str) -> int:
        """The latest annotator of the first of ``steps`` that has one, else the first annotator."""
        for step in steps:
            for i in range(len(self.annotators) - 1, -1, -1):
                if self.annotators[i].step == step:
                    return i
        return 0


def _table(d: dict, target: str, annotator: int, edits: list[Edit], edit_by: int) -> Table:
    cells = []
    for c in d.get("cells") or []:
        cell = Cell(start_row=c["row"], end_row=c["row"] + c.get("row_span", 1), start_col=c["col"],
                    end_col=c["col"] + c.get("col_span", 1), text=c.get("text", ""), box=c.get("bbox"),
                    column_header=bool(c.get("header", False)))
        cells.append(cell)
        if c.get("normalized") is not None:
            edits.append(Edit(annotator=edit_by, target=f"{target}/{cell.ref}", kind="normalized",
                              text=c["normalized"]))
    known = {"cells", "num_rows", "num_cols", "html"}
    return Table(annotator=annotator, target=target, cells=cells, html=d.get("html"),
                 num_rows=d.get("num_rows") or max((c.end_row for c in cells), default=0),
                 num_cols=d.get("num_cols") or max((c.end_col for c in cells), default=0),
                 **_ext({k: v for k, v in d.items() if k not in known}))


def upgrade_transcription(d: dict, page_id: str | None = None) -> Transcription:
    """A page/2 transcription (as a dict) in page/3."""
    if "annotators" in d:
        return Transcription.model_validate(d)
    src = dict(d.get("source") or {})
    sx = (src.get("extra") or {}).get("scale")
    source = Source(**{k: v for k, v in src.items() if k != "extra"}, scale=sx, **_ext(src.get("extra"), ("scale",)))
    steps = _Steps(d.get("steps") or [], src)
    layout = steps.of("layout", "recognition", "lines")
    lines_by = steps.of("lines", "recognition", "layout")
    reading_by = steps.of("recognition", "lines")
    order_by = steps.of("typography", "assignment", "ordering", "lines", "layout", "recognition")
    text_by = steps.of("typography", "layout", "recognition")
    norm_by = steps.of("normalization")
    extra = dict(d.get("extra") or {})

    t = Transcription(source=source, annotators=steps.annotators)
    # raw outputs
    passes = extra.get("passes") or ([{"raw": extra["raw"], "finish_reason": extra.get("finish_reason")}]
                                     if "raw" in extra else [])
    kept = extra.get("kept", 1)
    for i, p in enumerate(passes, start=1):
        settings = {k: p[k] for k in ("max_tokens", "temperature", "top_p", "preset") if k in p}
        t.outputs.append(RawOutput(annotator=reading_by, content=p.get("raw", ""), pass_=i, kept=(i == kept),
                                   settings=settings, finish_reason=p.get("finish_reason"),
                                   prompt_tokens=p.get("prompt_tokens"), completion_tokens=p.get("completion_tokens")))
    out = 0 if t.outputs else None
    if t.outputs:
        out = next((i for i, o in enumerate(t.outputs) if o.kept), 0)

    regions = sorted(enumerate(d.get("regions") or []),
                     key=lambda ir: (ir[1].get("reading_order") is None, ir[1].get("reading_order") or 0, ir[0]))
    for r in d.get("regions") or []:
        rid = _id(r["id"])
        rx = dict(r.get("extra") or {})
        t.regions.append(Region(annotator=layout, output=out, id=rid, box=r.get("bbox"), polygon=r.get("polygon"),
                                label=r.get("raw_label", ""), confidence=r.get("score"),
                                **_ext(rx, ("table", "formula", "generated", "printed"))))
        role, production = role_of_label(r["label"])
        t.classifications.append(Classification(annotator=text_by, target=rid, scheme="role", value=role))
        if production:
            t.classifications.append(Classification(annotator=layout, target=rid, scheme="production",
                                                    value=production))
        if r.get("heading_level") is not None:
            t.classifications.append(Classification(annotator=text_by, target=rid, scheme="heading_level",
                                                    value=str(r["heading_level"])))
        if (rx.get("table") or {}).get("cells") or (rx.get("table") or {}).get("html"):
            t.tables.append(_table(rx["table"], rid, steps.of("tables", "recognition", "layout"), t.edits, norm_by))
        if rx.get("formula") is not None:
            t.formulas.append(Formula(annotator=steps.of("formulas", "recognition", "layout"), target=rid,
                                      latex=rx["formula"]))
        if rx.get("generated"):
            g = rx["generated"]
            t.descriptions.append(Description(annotator=layout, output=out, target=rid, kind=g.get("kind", "description"),
                                              text=g.get("content", "")))
    restored = []                     # regions typography removed, with their text: back, classified removed
    for dropped in extra.get("retyper_dropped") or []:
        rid = _id(dropped["region_id"])
        if t.region(rid) is not None:
            continue
        t.regions.append(Region(annotator=layout, id=rid, label=dropped.get("raw_label", ""),
                                page2__reason=dropped.get("reason")))
        if dropped.get("label"):
            t.classifications.append(Classification(annotator=layout, target=rid, scheme="role",
                                                    value=role_of_label(dropped["label"])[0]))
        t.classifications.append(Classification(annotator=steps.of("typography"), target=rid, scheme="status",
                                                value="removed", confidence=dropped.get("confidence")))
        lid = _id((dropped.get("lines") or [f"{rid}_l0"])[0])
        restored.append(Line(annotator=lines_by, id=lid, region=rid,
                             reading=Reading(annotator=reading_by, text=dropped.get("text") or "")))

    lines = d.get("lines") or []
    for ln in lines:
        lid = _id(ln["id"])
        reading = None
        if ln.get("text") is not None:
            words = []
            for k, w in enumerate(ln.get("words") or []):
                wid = w.get("id")
                words.append(Word(text=w["text"], box=w.get("bbox"), confidence=w.get("confidence"),
                                  hyphen=w.get("hyphen", False), alternatives=w.get("alternatives") or [],
                                  id=None if wid in (None, f"{ln['id']}_w{k}") else wid, **_ext(w.get("extra"))))
            reading = Reading(annotator=reading_by, output=out, text=ln["text"], confidence=ln.get("confidence"),
                              alternatives=ln.get("alternatives") or [], words=words)
        t.lines.append(Line(annotator=lines_by, output=out if lines_by == reading_by else None, id=lid,
                            region=_id(ln["region_id"]) if ln.get("region_id") is not None else None,
                            box=ln.get("bbox"), polygon=ln.get("polygon"), baseline=ln.get("baseline"),
                            confidence=ln.get("score"), reading=reading, **_ext(ln.get("extra"))))
        if ln.get("normalized") is not None:
            t.edits.append(Edit(annotator=norm_by, target=lid, kind="normalized", text=ln["normalized"]))
    t.lines.extend(ln for ln in restored if t.line(ln.id) is None)
    ordered = sorted(enumerate(lines), key=lambda il: (il[1].get("reading_order", 0), il[0]))
    if regions or lines:
        t.orders.append(ReadingOrder(annotator=order_by,
                                     regions=[_id(r["id"]) for _, r in regions if r.get("reading_order") is not None],
                                     lines=[_id(ln["id"]) for _, ln in ordered],
                                     rows=[ln.get("row", 0) for _, ln in ordered]))

    rec = steps.of("recomposition")
    for p in d.get("paragraphs") or []:
        pid = _id(p["id"])
        t.ranges.append(Paragraph(annotator=rec, id=pid, parts=[_id(p["region_id"])] if p.get("region_id") else [],
                                  text=p.get("text", ""),
                                  rows=[ParagraphRow(lines=[_id(x) for x in row["lines"]],
                                                     charspan=[row["start"], row["end"]]) for row in p.get("rows", [])],
                                  decisions=[Decision(**dc) for dc in p.get("decisions", [])], **_ext(p.get("extra"))))
        if p.get("normalized") is not None:
            t.edits.append(Edit(annotator=norm_by, target=pid, kind="normalized", text=p["normalized"]))
        for key, kind in (("continues_from", "continues"), ("continues", "runs_into")):
            ref = p.get(key)
            if ref:
                target = _id(ref["id"]) if not ref.get("page_id") else f"{ref['page_id']}#{_id(ref['id'])}"
                t.links.append(Link(annotator=rec, kind=kind, source=pid, target=target))

    if d.get("language"):
        t.classifications.append(Classification(annotator=reading_by, target="", scheme="language",
                                                value=d["language"]))
    for k, v in _ext(extra, ("raw", "passes", "kept", "finish_reason", "retyper_dropped")).items():
        setattr(t, k, v)
    if d.get("docling") is not None:
        pass                                                   # a rendering: made again from the set
    return t


def page_2_to_3(row: dict) -> dict:
    """A stored page/2 row in page/3; a page/3 row unchanged."""
    if row.get("schema") == SCHEMA:
        return row
    if row.get("schema") not in (None, OLD):
        raise ValueError(f"cannot upgrade a page record of schema {row.get('schema')!r}")
    page = dict(row.get("page") or {})
    page["transcriptions"] = {name: upgrade_transcription(t, page.get("page_id")).model_dump(
        mode="json", by_alias=True, exclude_defaults=True) for name, t in (page.get("transcriptions") or {}).items()}
    return {**row, "schema": SCHEMA, "page": page}
