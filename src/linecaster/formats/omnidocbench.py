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
  (``tables="data"``, ``linecaster.evaluation.tables``): a contents list or a layout table is its text.
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
only ``\\w`` characters and CJK ideographs, so combining marks (Devanagari vowel signs, Arabic vowel marks, Hebrew
points, Thai vowels), punctuation and spaces are not compared, and nothing is put in NFC (``nfc`` as the export's
``strategy`` makes both sides alike); predicted text that matches no ground-truth element, and predicted tables that
match no ground-truth table, are not counted; captions and footnotes are matched but not scored; its "overall" needs
its formula metric CDM (TeX Live) and pages with tables and formulas. It runs on Python before 3.12, in an
environment of its own. linecaster's own scorer (``linecaster.evaluation``) is the measure for scripts with marks."""
from __future__ import annotations

from typing import Any

from linecaster.data.policy import DEFAULT_POLICY, RenderingPolicy
from linecaster.data.transcription import Table, Transcription
# the traversal the scorer's elements share: both views cut a page alike
from linecaster.evaluation.elements import SKIP, display_formula, reading_blocks, table_text  # noqa: F401

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








def truth_page(page_id: str, t: Transcription, policy: RenderingPolicy = DEFAULT_POLICY,
               attributes: dict[str, Any] | None = None, tables: str = "data") -> dict:
    """The ground truth ``t`` of page ``page_id`` as an entry of OmniDocBench's ground-truth JSON (module docstring);
    ``attributes`` its ``page_attribute`` (the groups the harness reports by). ``tables``: which of its tables are
    tables to the harness: ``data`` (``linecaster.evaluation.tables.table_kind``: printed as tables; a contents list
    or layout table is its text, ``text_block``, so its words are still scored) or ``all``."""
    from linecaster.evaluation.tables import table_kind

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
    from linecaster.evaluation.tables import table_kind

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
    """A ground-truth page's slices (``linecaster.evaluation.slices``) as OmniDocBench page attributes (``yes``/``no``),
    by which its evaluation groups its page results."""
    from linecaster.evaluation.slices import page_slices

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

    from linecaster.data import Page
    from linecaster.data.transcription import producer
    from linecaster.data.upgrade import upgrade

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
    from linecaster.catalog.registry import catalog

    return catalog().strategy(strategy, use="output").text


# ------------------------------------------------------------------------------------ reading its ground truth
# ``from_omnidocbench``: one entry of OmniDocBench's ground-truth JSON (a page) read into a ground-truth transcription,
# so that runs are scored on its pages by linecaster's own scorer (``import.omnidocbench.v1``, preset
# ``omnidocbench-import``; ``entries`` splits the JSON's list into its pages).
import re
from collections.abc import Iterator
from typing import NamedTuple

#: OmniDocBench's ``category_type`` -> linecaster's content role (``CATEGORIES`` read back where it names one); the
#: category stays the region's ``label``, verbatim; a category not listed is the role ``other``
ROLES = {
    "title": "heading", "text_block": "paragraph", "figure": "picture", "figure_caption": "caption",
    "figure_footnote": "footnote", "table": "table", "table_caption": "caption", "table_footnote": "footnote",
    "equation_isolated": "formula", "equation_caption": "other", "header": "header", "footer": "footer",
    "page_number": "page_number", "page_footnote": "footnote", "abandon": "other", "code_txt": "code",
    "code_txt_caption": "caption", "reference": "reference",
}
#: categories of content OmniDocBench's annotators discarded (``abandon``): classified ``status`` ``suppressed``, as an
#: element marked ``ignore`` is, so that no text holds it
DISCARDED = frozenset({"abandon"})
#: OmniDocBench's language values (a page's ``language``, a block's ``text_language`` or a table's ``language``, without
#: their ``text_`` or ``table_`` prefix) -> BCP 47; English and Chinese mixed is ``mul`` (BCP 47's multiple languages)
LANGUAGES = {"en": "en", "english": "en", "simplified_chinese": "zh-Hans", "en_ch_mixed": "mul"}
#: the keys of an element that its region, lines, table or formula hold; every other key is kept on the region as an
#: extension field ``omnidocbench__<key>``
_READ = frozenset({"category_type", "poly", "ignore", "order", "text", "html", "line_with_spans", "merge_list"})
#: an inline formula in a block's text, where its spans do not say where they are: ``$…$``, as OmniDocBench writes one
_INLINE = re.compile(r"(?<!\$)\$(?!\$)([^$\n]+?)(?<!\$)\$(?!\$)")
_NAME = re.compile(r"[^a-z0-9_]+")


def omnidocbench_language(value: Any) -> str | None:
    """An OmniDocBench language value as a BCP 47 tag (``LANGUAGES``), else ``None``."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    for prefix in ("text_", "table_"):
        v = v.removeprefix(prefix)
    return LANGUAGES.get(v)


def _extension(key: str) -> str | None:
    name = _NAME.sub("_", str(key).lower()).strip("_")
    return f"omnidocbench__{name}" if name and name[0].isalpha() else (f"omnidocbench__k{name}" if name else None)


def _points(poly: Any) -> list[list[float]] | None:
    """``poly`` (x1, y1, x2, y2, ...: OmniDocBench's corners) as points, or ``None``."""
    if not isinstance(poly, list) or len(poly) < 6 or len(poly) % 2:
        return None
    try:
        return [[float(poly[i]), float(poly[i + 1])] for i in range(0, len(poly), 2)]
    except (TypeError, ValueError):
        return None


def _box(points: list[list[float]] | None) -> list[float] | None:
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


def _union(a: list[float], b: list[float]) -> list[float]:
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    return [x0, y0, max(a[0] + a[2], b[0] + b[2]) - x0, max(a[1] + a[3], b[1] + b[3]) - y0]


def _same_row(row: list[float], box: list[float]) -> bool:
    """Whether a span's box lies on the row of ``row`` (the boxes of its spans so far): they overlap vertically by at
    least half the lower of the two."""
    overlap = min(row[1] + row[3], box[1] + box[3]) - max(row[1], box[1])
    return overlap >= 0.5 * min(row[3], box[3]) and overlap > 0


def _span_text(span: dict) -> str:
    value = span.get("text")
    if value is None:
        value = span.get("latex")
    return value.strip() if isinstance(value, str) else ""


class _Line(NamedTuple):
    """One line of a block as ``_text_lines`` cuts it: its text, box, inline formulas (``(start, end, LaTeX)``) and
    the halves of divided words on it (``(start, end, the whole word)``)."""

    text: str
    box: list[float] | None
    formulas: list[tuple[int, int, str]]
    joined: list[tuple[int, int, str]]


def _text_lines(text: str, spans: list[dict]) -> list[_Line]:
    """A block's ``text`` as its lines. With spans (``line_with_spans``): each row of spans a line, its box their
    union, cut from the block's text where the row's first span begins, the spans written in LaTeX (``$…$``) its
    inline formulas. Where a row's last span ends in a division mark the block's text dropped (``evap-`` of
    ``evaporator``), the line keeps the mark, as the span prints it, and both halves name the whole word, the block
    text's (a ``joined`` edit each). Where a span is not found in the text in order, or without spans: a line per
    line of the text, without boxes, and ``$…$`` its inline formulas."""
    rows: list[tuple[list[float], list[dict]]] = []
    ok = bool(spans)
    for s in spans:
        box = _box(_points(s.get("poly")))
        if box is None:
            ok = False
            break
        if not _span_text(s):
            continue
        if rows and _same_row(rows[-1][0], box):
            rows[-1] = (_union(rows[-1][0], box), rows[-1][1] + [s])
        else:
            rows.append((box, [s]))
    found: list[list[tuple[int, int, dict]]] = []
    divided: set[int] = set()                     # rows whose last span's division mark the text dropped
    pos = 0
    for r, (_, row) in enumerate(rows if ok else ()):
        located = []
        for s in row:
            piece = _span_text(s)
            k = text.find(piece, pos)
            if k < 0 and piece.endswith("-") and s is row[-1] and len(piece) > 1:
                k = text.find(piece[:-1], pos)
                if k >= 0 and k + len(piece) - 1 < len(text) and not text[k + len(piece) - 1].isspace():
                    piece = piece[:-1]
                    divided.add(r)
                else:
                    k = -1
            if k < 0:
                ok = False
                break
            located.append((k, k + len(piece), s))
            pos = k + len(piece)
        if not ok:
            break
        found.append(located)
    if not (ok and found):
        return [_Line(x.strip(), None, _inline(x.strip()), []) for x in text.split("\n") if x.strip()]
    starts = [0] + [row[0][0] for row in found[1:]] + [len(text)]
    out: list[_Line] = []
    for r, located in enumerate(found):
        a, b = starts[r], starts[r + 1]
        segment = text[a:b]
        lead = len(segment) - len(segment.lstrip())
        line = segment.strip()
        if not line:
            continue
        if "\n" in line:                            # a line break of the text inside a row: its lines, unboxed
            out += [_Line(x.strip(), None, _inline(x.strip()), []) for x in line.split("\n") if x.strip()]
            continue
        formulas = [(k - a - lead, e - a - lead, _span_text(s)[1:-1].strip()) for k, e, s in located
                    if s.get("category_type") != "equation_isolated" and len(_span_text(s)) > 1
                    and _span_text(s).startswith("$") and _span_text(s).endswith("$")]
        joined: list[tuple[int, int, str]] = []
        if r - 1 in divided and out and out[-1].text.endswith("-") and b > a:      # the second half
            head = re.match(r"\S+", line)
            if head:
                whole = out[-1].joined[-1][2] if out[-1].joined else head.group(0)
                joined.append((0, head.end(), whole))
        if r in divided and r + 1 < len(found):                                   # the first half: the mark back
            nxt = text[starts[r + 1]:].lstrip()
            tail = re.search(r"\S+$", line)
            if tail and nxt and not nxt[0].isspace():
                whole = tail.group(0) + re.match(r"\S*", nxt).group(0)
                line += "-"
                joined.append((tail.start(), len(line), whole))
        out.append(_Line(line, rows[r][0], formulas, joined))
    return out


def _inline(line: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(1).strip()) for m in _INLINE.finditer(line) if m.group(1).strip()]


def _unwrapped(latex: str) -> str:
    """A display formula's LaTeX without its ``$$`` (or ``$``, ``\\[ \\]``) delimiters."""
    s = latex.strip()
    for a, b in (("$$", "$$"), ("\\[", "\\]"), ("$", "$")):
        if s.startswith(a) and s.endswith(b) and len(s) >= len(a) + len(b):
            return s[len(a):len(s) - len(b)].strip()
    return s


def page_id(entry: dict) -> str:
    """The page id of an entry: its ``page_info.image_path``'s file name without the extension (the key a prediction
    file is found by)."""
    path = str((entry.get("page_info") or {}).get("image_path") or "")
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    if not stem or "#" in stem:
        raise ValueError(f"an OmniDocBench entry's image_path {path!r} gives no page id (empty, or with '#')")
    return stem


def entries(path) -> Iterator[tuple[str, dict]]:
    """``(page id, entry)`` for each entry of OmniDocBench's ground-truth JSON (a list of pages; a local path or any
    fsspec URI): the rows of a table ``pipelines/import_transcriptions.py`` reads with ``--data-key`` (each entry's
    JSON) and the importer ``omnidocbench-import``."""
    import json

    if "://" in str(path):
        import fsspec

        with fsspec.open(str(path), "rt", encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"{path}: OmniDocBench's ground truth is a JSON list of pages")
    for entry in data:
        yield page_id(entry), entry


def from_omnidocbench(entry: dict | str | bytes, ground_truth: bool = True, uri: str | None = None) -> Transcription:
    """One entry of OmniDocBench's ground-truth JSON (a page: ``layout_dets``, ``page_info``, ``extra``; or its JSON)
    as a transcription, by its annotators (one annotator, kind ``human``; ``ground_truth=False``: ``file``):

    * every element (``layout_dets``) a region, ``r<anno_id>``: its ``poly`` the polygon (and box), its category the
      ``label`` and, by ``ROLES``, its ``role``; ``ignore`` and the discarded category (``abandon``) a ``status``
      ``suppressed``; its block-level ``attribute`` and any other key kept as extension fields
      (``omnidocbench__attribute``, ``omnidocbench__anno_id``, a table's ``omnidocbench__latex``, ...), and its
      language (``text_language``, a table's ``language``) a ``language`` classification where it is not the page's;
    * its text as lines (``_text_lines``: the rows of its ``line_with_spans``, or of its ``merge_list``'s, else the
      text's lines), inline formulas (``$…$``) as ``Formula`` annotations of their spans, the text kept as written;
    * a table's ``html`` a ``Table`` (``linecaster.formats.html_table``), a display formula's ``latex``
      (``equation_isolated``) a ``Formula`` of its region, without its ``$$``; neither has lines;
    * ``order`` the reading order of the regions that have one, and of their lines (OmniDocBench leaves page furniture
      and discarded elements unordered: they come last, in the entry's order);
    * relations (``extra.relation``): ``parent_son`` to a caption a ``caption_of`` link, to a footnote a ``note_of``
      link; ``truncated`` (a paragraph cut by the layout) a ``continues`` link from the later part; others kept as the
      transcription's extension field ``omnidocbench__relation``;
    * ``page_info``: ``image_path`` the source's ``record``, ``width`` and ``height`` its image size, and every
      ``page_attribute`` an extension field of the source (``omnidocbench__data_source``, ``omnidocbench__layout``,
      ``omnidocbench__special_issue``, ``omnidocbench__language``, ...); the language also a page classification
      (``LANGUAGES``: ``en``, ``zh-Hans``, ``mul`` for English and Chinese mixed)."""
    import json

    from linecaster.data.transcription import Annotator, Edit, Formula, Link, Source
    from linecaster.formats.html_table import table_from_html

    if isinstance(entry, (str, bytes)):
        entry = json.loads(entry)
    info = entry.get("page_info") or {}
    attributes = info.get("page_attribute") or {}
    extensions = {name: value for key, value in attributes.items() if (name := _extension(key)) is not None}
    if info.get("page_no") is not None:
        extensions["omnidocbench__page_no"] = info["page_no"]
    size = {k: int(info[k]) for k in ("width", "height") if isinstance(info.get(k), int | float) and info[k] > 0}
    t = Transcription(source=Source(kind="ground_truth" if ground_truth else "converted", format="omnidocbench",
                                    uri=uri, record=info.get("image_path") or None,
                                    image_width=size.get("width"), image_height=size.get("height"), **extensions))
    a = t.add_annotator(Annotator(kind="human" if ground_truth else "file", step="transcription", name="omnidocbench"))
    page_language = omnidocbench_language(attributes.get("language"))
    if page_language:
        t.classify(a, "", "language", page_language)
    dets = [d for d in entry.get("layout_dets") or [] if isinstance(d, dict)]
    anno = [d.get("anno_id") for d in dets]
    unique = all(isinstance(x, int) and not isinstance(x, bool) for x in anno) and len(set(anno)) == len(anno)
    rid = {id(d): f"r{d['anno_id']}" if unique else f"r{k}" for k, d in enumerate(dets)}
    ranked = sorted((d for d in dets if isinstance(d.get("order"), int | float)), key=lambda d: d["order"])
    order_regions, order_lines, order_rows = [], [], []
    for d in ranked + [d for d in dets if not isinstance(d.get("order"), int | float)]:
        region, category = rid[id(d)], str(d.get("category_type") or "")
        polygon = _points(d.get("poly"))
        latex = d.get("latex") if isinstance(d.get("latex"), str) else None
        formula = category == "equation_isolated" and bool(latex and _unwrapped(latex))
        fields = {name: v for k, v in d.items() if k not in _READ and not (k == "latex" and formula)
                  and v not in (None, "", [], {}) and (name := _extension(k)) is not None}
        t.add_region(a, region, _box(polygon), polygon, label=category, role=ROLES.get(category, "other"), **fields)
        if d.get("ignore") is True or category in DISCARDED:
            t.classify(a, region, "status", "suppressed")
        block = d.get("attribute") if isinstance(d.get("attribute"), dict) else {}
        language = omnidocbench_language(block.get("text_language") or block.get("language"))
        if language and language != page_language:
            t.classify(a, region, "language", language)
        lines: list[str] = []
        if formula:
            t.formulas.append(Formula(annotator=a, target=region, latex=_unwrapped(latex)))
        elif category == "table" and isinstance(d.get("html"), str) and d["html"].strip() and (
                table := table_from_html(d["html"], a, region)) is not None:
            t.tables.append(table)
        elif isinstance(d.get("text"), str) and d["text"].strip():
            spans = [s for s in d.get("line_with_spans") or [] if isinstance(s, dict)]
            if not spans:
                spans = [s for m in d.get("merge_list") or [] if isinstance(m, dict)
                         for s in m.get("line_with_spans") or [] if isinstance(s, dict)]
            for j, cut in enumerate(_text_lines(d["text"], spans)):
                line = t.add_line(a, f"{region}_l{j}", cut.box, region=region, text=cut.text).id
                lines.append(line)
                t.formulas += [Formula(annotator=a, target=f"{line}[{s}:{e}]", latex=x) for s, e, x in cut.formulas
                               if x]
                t.edits += [Edit(annotator=a, target=f"{line}[{s}:{e}]", kind="joined", text=w)
                            for s, e, w in cut.joined]
        if d in ranked:
            order_regions.append(region)
            order_lines += lines
            order_rows += range(len(lines))
    if order_regions:
        t.add_order(a, order_regions, order_lines, order_rows)
    by_anno = {d.get("anno_id"): rid[id(d)] for d in dets} if unique else {}
    kept = []
    for rel in (entry.get("extra") or {}).get("relation") or []:
        kind = rel.get("relation_type") or rel.get("relation")
        src, tgt = by_anno.get(rel.get("source_anno_id")), by_anno.get(rel.get("target_anno_id"))
        son = t.region(tgt).label if tgt else ""
        if src and tgt and kind == "parent_son" and ROLES.get(son) == "caption":
            t.links.append(Link(annotator=a, kind="caption_of", source=tgt, target=src))
        elif src and tgt and kind == "parent_son" and ROLES.get(son) == "footnote":
            t.links.append(Link(annotator=a, kind="note_of", source=tgt, target=src))
        elif src and tgt and kind == "truncated":
            t.links.append(Link(annotator=a, kind="continues", source=tgt, target=src))
        else:
            kept.append(rel)
    if kept:
        t.omnidocbench__relation = kept
    return t
