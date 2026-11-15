"""``DocumentBuilder``: a page's or an item's transcriptions as one ``Document`` (``linecaster.document.model``).

The document is a rendering of the annotation sets, made again whenever it is needed (never stored with them). A
**rendering policy** (``linecaster.data.policy``, ``DEFAULT_POLICY`` by default) puts each region in a layer by its
content role, production and status: page headers, footers and page numbers in the **furniture** layer (the
serializers choose whether to include it), regions in ``none`` (removed, suppressed, duplicate, separators) and
``metadata`` left out, and lines it puts in ``none`` (a line assignment's duplicates); descriptions are never text.

**Without paragraphs** (diplomatic composition): one block per region, in reading order (regions without an order
last, in list order), its text one visual row per line (the region's lines on the same row joined with a space, rows
joined with ``\\n``; each line's text as written, its ``nfc`` and ``joined`` edits applied:
``linecaster.text.recomposition.region_rows``), its lines' formatting and languages as spans, one origin with the
region's box. A text region that continues another (its own ``continues`` link: a transcription whose regions are
its paragraphs, such as an imported ground truth) is appended to that one's block, joined as recomposition joins
rows: a division mark before a lowercase letter removed (``resolve_mark``), else a space unless UAX #14 joins the
words (``separator``); a block of several rows (verse, a stanza across a page break) goes on with a new row.

**With paragraphs** (a recomposition ran: its latest recomposition's, ``linecaster.text.recomposition.paragraphs``):
one block per paragraph of a text region, an origin per row (its box and character span), a paragraph that continues
another (its ``continues`` link by the same annotator, in an earlier region or on an earlier page) appended to that
one's block. The recomposition decides; the builder only composes.

The block's kind comes from the region's content role (``block_kind``): a title, a heading at the region's heading
level (1 when unset), a paragraph, list item, caption, note, page header or footer; a region with a table structure
(``Transcription.table``) a table by the policy's table rules (``TableRules``: one cell as text, one column as lines,
a one-row table after a table of its width that table's next row, holes filled); one with a formula
(``Transcription.formula``) a formula, its LaTeX the text; any other region (picture, chart, a table without a
structure) a picture, with the text read inside it and the image its source names (a ``<engine>__src`` extension).
Empty regions make no block.

``sections``: every title or heading opens a section that holds it and every block after it up to the next one,
across pages (``Block.section``); blocks before the first stay outside.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from ..data.geometry import BBox
from ..data.policy import DEFAULT_POLICY, RenderingPolicy
from ..data.refs import parse
from ..data.transcription import AS_WRITTEN, Cell, Line, Region, Table, Transcription
from ..formats._xml import heading_level, hidden_line
from ..text.recomposition import continuation, ends_with_mark, paragraphs as paragraphs_of, resolve_mark, separator
from ..text.typography import line_bbox, zone_bbox
from .model import Block, Document, Grid, Origin, Page, Span

#: content role -> block kind (roles not listed: paragraph); page numbers are placed (``block_kind``)
KIND_OF_ROLE: dict[str, str] = {
    "paragraph": "paragraph", "heading": "heading", "title": "title", "caption": "caption",
    "list_item": "list_item", "list_label": "list_item", "toc_entry": "toc_entry", "footnote": "footnote",
    "footnote_continued": "footnote", "endnote": "footnote", "reference": "reference", "code": "code",
    "table": "table", "formula": "formula", "chemistry": "formula", "music": "picture", "picture": "picture",
    "chart": "picture", "map": "picture", "advert": "picture", "form": "picture", "key_value": "picture",
    "header": "page_header", "footer": "page_footer", "catch_word": "page_footer", "signature_mark": "page_footer",
    "separator": "picture", "noise": "picture",
}
#: the kinds whose blocks are text (a region of another kind with text is a picture with it)
TEXT_KINDS = frozenset({"title", "heading", "paragraph", "list_item", "caption", "footnote", "toc_entry", "reference",
                        "code", "page_header", "page_footer", "formula"})
#: a page number is a page header when its centre lies in the top ``HEADER_ZONE`` of the page (or without a box)
HEADER_ZONE = 0.15
NOT_RENDERED = ("metadata", "none")


def block_kind(t: Transcription, region: str) -> str:
    """The kind of block a region makes, from its content role (``KIND_OF_ROLE``): a page number a page header in
    the top ``HEADER_ZONE`` of the page or without a box, else a page footer."""
    role = t.role(region) or "paragraph"
    if role == "page_number":
        r, height = t.region(region), t.source.image_height
        if r is not None and r.box is not None and height:
            return "page_header" if r.box[1] + r.box[3] / 2 < HEADER_ZONE * height else "page_footer"
        return "page_header"
    return KIND_OF_ROLE.get(role, "paragraph")


def _box(b: BBox | None) -> list[float] | None:
    return None if b is None else [b.x0, b.y0, b.x1, b.y1]


def _zone_box(z) -> BBox | None:
    return zone_bbox(z) if z.polygon or z.box else None


def _picture_file(r: Region) -> str | None:
    return next((v for k, v in r.extensions.items() if k.endswith("__src") and isinstance(v, str)), None)


class DocumentBuilder:
    """One ``Document`` for one page or for all pages of an item, in order (``add_page`` once per page). Page ``n``
    of the document is the ``n``-th page added."""

    def __init__(self, name: str = "document", sections: bool = False, policy: RenderingPolicy = DEFAULT_POLICY):
        self.doc = Document(name=name)
        self.sections, self.policy = sections, policy
        self._section: str | None = None          # the heading block whose section is open
        self._last_table: Block | None = None      # the table a one-row table may join (merge_single_rows)
        self._items: dict[tuple[str, str], tuple[Block, str | None]] = {}   # (page key, id) -> its block, separator
        self.pages = 0

    # ------------------------------------------------------------------ pages
    def add_page(self, t: Transcription, width: int | None = None, height: int | None = None,
                 page_no: int | None = None, page_id: str | None = None) -> int:
        """Adds one page; ``page_id`` names it for what is continued from it (``<page_id>#<id>`` references)."""
        self.pages += 1
        page_no = page_no or self.pages
        self.doc.pages.append(Page(page=page_no, id=page_id, width=width or t.source.image_width,
                                   height=height or t.source.image_height))
        by_region: dict[str | None, list[Line]] = {}
        for ln in t.lines:
            if not hidden_line(t, ln, self.policy):
                by_region.setdefault(t.region_of(ln), []).append(ln)
        page = _PageContext(page_no, page_id if page_id is not None else f"#{page_no}", t)
        paragraphs: dict[str | None, list] = {}
        for p in page.paragraphs:
            paragraphs.setdefault(p.region, []).append(p)
        for r in t.ordered_regions():
            layer = self.policy.layer_of(t, r.id)
            if layer in NOT_RENDERED:
                continue
            page.layer = layer
            self._add_region(page, r, by_region.get(r.id, []), paragraphs.get(r.id) if page.recomposed else None)
        if None in paragraphs and not t.regions:          # a text-only page: its paragraphs without a region
            page.layer = "body"
            self._add_paragraphs(page, None, "paragraph", paragraphs[None])
        return page_no

    def build(self) -> Document:
        """The document, every origin's box clamped to its page (a layout box often reaches a few pixels past the
        edge); the transcriptions keep their boxes."""
        size = {pg.page: (pg.width, pg.height) for pg in self.doc.pages}
        for block in self.doc.blocks:
            for o in block.origins:
                w, h = size.get(o.page, (None, None))
                if o.box is not None and w and h:
                    x0, y0, x1, y1 = o.box
                    o.box = [min(max(float(x0), 0.0), float(w)), min(max(float(y0), 0.0), float(h)),
                             min(max(float(x1), 0.0), float(w)), min(max(float(y1), 0.0), float(h))]
        return self.doc

    # ---------------------------------------------------------------- blocks
    def _block(self, kind: str, page: "_PageContext", text: str = "", opens: bool = True, **fields) -> Block:
        """A new block; a title or heading opens its section unless not ``opens``."""
        b = Block(id=f"b{len(self.doc.blocks)}", kind=kind, layer=page.layer, text=text, **fields)
        if kind in ("title", "heading") and self.sections and opens:
            self._section = b.id
        b.section = self._section if self.sections else None
        self.doc.blocks.append(b)
        return b

    def _add_region(self, page: "_PageContext", r: Region, lines: list[Line], paragraphs: list | None) -> None:
        t = page.t
        b = _zone_box(r)
        kind, role = block_kind(t, r.id), t.role(r.id)
        level = (heading_level(t, r.id) or 1) if kind == "heading" else None
        f, table = t.formula(r.id), t.table(r.id)
        if paragraphs is not None and f is None and table is None and kind in TEXT_KINDS:
            self._add_paragraphs(page, r, kind, paragraphs, level)
            return
        if page.recomposed and f is None and table is None and kind in TEXT_KINDS:
            return                    # recomposed, no paragraphs: the region has no text
        if table is not None:
            self._add_table(page, r, table, b, role)
            return
        self._last_table = None                 # anything but a table ends the run a one-row table may join
        origin = lambda text: Origin(page=page.page_no, region=r.id, lines=[ln.id for ln in lines], box=_box(b),
                                     span=[0, len(text)])
        if f is not None:
            if f.latex.strip():
                self._block("formula", page, f.latex, role=role, origins=[origin(f.latex)])
            return
        text, spans = _region_text(t, lines)
        if kind in TEXT_KINDS:
            if text.strip():
                self._add_region_text(page, r, kind, role, level, text, spans, origin(text))
        else:
            self._block("picture", page, text if text.strip() else "", role=role, spans=spans, file=_picture_file(r),
                        origins=[origin(text)])

    def _add_region_text(self, page: "_PageContext", r: Region, kind: str, role, level, text: str,
                         spans: list[Span], origin: Origin) -> None:
        """A text region's block, or its text appended to the block of the region it continues; a region that runs
        on leaves its block for the region it runs into."""
        t = page.t
        continued = self._items.get((page.key, r.id)) if _region_link(t, r.id, "continues") else None
        if continued is not None:
            block, _ = continued
            head = block.text
            if "\n" in head or "\n" in text:          # verse: a block of several rows goes on with a new row
                sep = "\n"
            elif ends_with_mark(head) and resolve_mark(head, text)[0]:
                head, sep = head.rstrip()[:-1], ""
            else:
                sep = separator(head, text)
            offset = len(head) + len(sep)
            block.text = head + sep + text
            block.spans = [s for s in block.spans if s.start < len(head)] + \
                [s.model_copy(update={"start": s.start + offset, "end": s.end + offset}) for s in spans]
            origin.span = [offset, len(block.text)]
            block.origins.append(origin)
        else:
            block = self._block(kind, page, text, role=role, level=level, spans=spans, origins=[origin])
        runs_into = _region_link(t, r.id, "runs_into")
        if runs_into is not None:
            ref = parse(runs_into)
            self._items[(ref.page or page.key, ref.id)] = (block, None)

    def _add_table(self, page: "_PageContext", r: Region, table: Table, b, role) -> None:
        """A table by the policy's table rules: one cell as text, one column as lines, a single row joined to the
        table before it, holes filled."""
        rules = self.policy.tables
        rows: dict[int, list[Cell]] = {}
        for c in sorted(table.cells, key=lambda c: (c.start_row, c.start_col)):
            rows.setdefault(c.start_row, []).append(c)
        origin = Origin(page=page.page_no, region=r.id, box=_box(b))
        if rules.single_cell == "text" and len(table.cells) == 1 or rules.single_column == "lines" \
                and table.num_cols == 1:
            text, formulas = "", []
            for k, row in enumerate(rows.values()):          # rows by "\n", a row's cells by " "
                text += "\n" if k else ""
                for j, c in enumerate(x for x in row if x.text):
                    text += " " if j else ""
                    formulas += [(len(text) + f[0], len(text) + f[1]) for f in c.formulas]
                    text += c.text
            lead = len(text) - len(text.lstrip())
            text = text.strip()
            if text:
                origin.span = [0, len(text)]
                block = self._block("paragraph", page, text, role=role, origins=[origin])
                block.spans += [Span(start=a - lead, end=e - lead, formula=True) for a, e in formulas
                                if 0 <= a - lead and e - lead <= len(text)]
            self._last_table = None
            return
        grid = _grid(table, rules.fill_holes)
        continued = self._items.get((page.key, r.id)) if _region_link(page.t, r.id, "continues") else None
        if continued is not None and continued[0].grid is not None:     # a table the previous page began
            block = continued[0]
            _continue_grid(block.grid, grid, any(ln.kind == "continues" and ln.source.startswith(f"{r.id}/")
                                                 for ln in page.t.links))
            block.origins.append(origin)
            self._last_table = block
            self._table_runs_into(page, r, block)
            return
        last = self._last_table
        if rules.merge_single_rows and table.num_rows == 1 and last is not None \
                and last.grid.num_cols == table.num_cols:
            n = last.grid.num_rows
            last.grid.cells += [c.model_copy(update={"start_row": n, "end_row": n + 1}) for c in grid.cells]
            last.grid.num_rows += 1
            last.origins.append(origin)
            return
        self._last_table = self._block("table", page, role=role, grid=grid, origins=[origin])
        self._table_runs_into(page, r, self._last_table)

    def _table_runs_into(self, page: "_PageContext", r: Region, block: Block) -> None:
        runs_into = _region_link(page.t, r.id, "runs_into")
        if runs_into is not None:
            ref = parse(runs_into)
            self._items[(ref.page or page.key, ref.id)] = (block, None)

    def _add_paragraphs(self, page: "_PageContext", r: Region | None, kind: str, paragraphs: list,
                        level: int | None = None) -> None:
        """A text region's paragraphs: one block each; a region of one paragraph without a letter (a page number)
        a block of its kind that opens no section; a paragraph that continues another appended to that one's
        block, its rows' character spans after the text before it."""
        t = page.t
        role = t.role(r.id) if r is not None else None
        standalone = len(paragraphs) == 1 and not any(ch.isalpha() for ch in paragraphs[0].text)
        for p in paragraphs:
            continues = continuation(t, p, "continues")
            continued = None if standalone or continues is None else self._items.get((page.key, p.id))
            if continued is not None:
                block, sep = continued
                offset = len(block.text) + len(sep or "")
                block.text = block.text + (sep or "") + p.text
                block.origins.extend(self._row_origins(page, r, p, offset))
            else:
                block = self._block(kind, page, p.text, opens=not standalone, role=role, level=level,
                                    origins=self._row_origins(page, r, p))
            runs_into = continuation(t, p, "runs_into")
            if runs_into is not None:
                ref = parse(runs_into)
                sep = next((d.separator for d in reversed(p.decisions) if d.kind == "continuation"), None) or ""
                self._items[(ref.page or page.key, ref.id)] = (block, sep)

    def _row_origins(self, page: "_PageContext", r: Region | None, p, offset: int = 0) -> list[Origin]:
        """One origin per row of paragraph ``p`` that has a box, its character span shifted by ``offset``. A
        division mark removed at a continuation stays in its row's span (the row's span as recognized, the mark
        included), so the last row's span ends one character later then."""
        last = len(p.rows) - 1
        removed_at_end = continuation(page.t, p, "runs_into") is not None and any(
            d.kind == "mark_removed" and d.row == last for d in p.decisions)
        out = []
        for k, row in enumerate(p.rows):
            b = paragraph_box(row, page.lines)
            if b is None:
                continue
            start, end = row.charspan
            end += 1 if removed_at_end and k == last else 0
            out.append(Origin(page=page.page_no, region=r.id if r is not None else None, lines=list(row.lines),
                              box=_box(b), span=[start + offset, end + offset]))
        if not out and r is not None:            # text-only rows: the region's box
            out.append(Origin(page=page.page_no, region=r.id, box=_box(_zone_box(r)),
                              span=[offset, offset + len(p.text)]))
        return out


def paragraph_box(row, lines_by_id: dict[str, Line]) -> BBox | None:
    """The box of one row of a paragraph (``ParagraphRow``): the union of its lines' boxes (``line_bbox``), as
    ``region_rows`` makes it; None without geometry."""
    lines = [lines_by_id[i] for i in row.lines if i in lines_by_id]
    if not lines or not all(ln.polygon or ln.box for ln in lines):
        return None
    boxes = [line_bbox(ln) for ln in lines]
    return BBox(min(x.x0 for x in boxes), min(x.y0 for x in boxes), max(x.x1 for x in boxes), max(x.y1 for x in boxes))


def _region_text(t: Transcription, lines: list[Line]) -> tuple[str, list[Span]]:
    """A region's text, one visual row per line (``region_rows``' text: lines on a row joined with a space, rows
    with ``\\n``), and its lines' formatting, languages and inline formulas (``Transcription.formulas`` on a span of a
    line) as spans of it; where a line's text as written differs from its reading (an edit of the whole line, as a
    word joined across pages), the spans move with the text they cover (``_moved``), a span on removed text goes."""
    rows = t.rows()
    grouped: dict[int, list[Line]] = {}
    for ln in lines:
        grouped.setdefault(rows.get(ln.id, 0), []).append(ln)
    languages: dict[str, list[tuple[int, int, str]]] = {}
    for c in t.classifications:
        if c.scheme == "language" and "[" in str(c.target):
            p = parse(str(c.target))
            if p.span is not None:
                languages.setdefault(p.id, []).append((p.span[0], p.span[1], str(c.value)))
    formulas: dict[str, list[tuple[int, int]]] = {}
    for f in t.formulas:
        if "[" in str(f.target):
            p = parse(str(f.target))
            if p.span is not None:
                formulas.setdefault(p.id, []).append(p.span)
    text, spans, row_texts = "", [], []
    for k in sorted(grouped):
        parts = []
        for ln in grouped[k]:
            x = t.text_of(ln, AS_WRITTEN)
            if not x:
                continue
            at = len(text) + (1 if row_texts else 0) + sum(len(s) + 1 for s in parts)
            move = _moved(ln.reading.text if ln.reading is not None else x, x)
            for f in (ln.reading.formatting if ln.reading is not None else []):
                a, e = move(*(f.charspan or (0, len(ln.reading.text))))
                if e > a and (f.bold or f.italic or f.underline or f.strikethrough or f.script != "baseline"):
                    spans.append(Span(start=at + a, end=at + e, bold=f.bold, italic=f.italic, underline=f.underline,
                                      strikethrough=f.strikethrough, script=f.script))
            for a, e, lang in languages.get(ln.id, []):
                a, e = move(a, e)
                if e > a:
                    spans.append(Span(start=at + a, end=at + e, language=lang))
            for a, e in formulas.get(ln.id, []):
                a, e = move(a, e)
                if e > a:
                    spans.append(Span(start=at + a, end=at + e, formula=True))
            parts.append(x)
        row = " ".join(parts)                  # a row of empty lines stays, as an empty row
        text += ("\n" if row_texts else "") + row
        row_texts.append(row)
    return text, spans


def _moved(old: str, new: str):
    """A function moving a span ``[start, end)`` of ``old`` onto ``new`` (another form of the same text): through
    the parts both share unchanged; a span's start in a changed part goes to that part's start, its end to its end
    (a span on a half that became the whole word covers the word; one on removed text is empty)."""
    if old == new:
        return lambda a, e: (a, e)
    ops = SequenceMatcher(None, old, new, autojunk=False).get_opcodes()

    def at(pos: int, end: bool) -> int:
        for tag, i1, i2, j1, j2 in (reversed(ops) if end else ops):
            if i1 <= pos <= i2:
                return j1 + pos - i1 if tag == "equal" else (j2 if end else j1)
        return len(new)

    return lambda a, e: (at(a, False), at(e, True))


def _continue_grid(grid: Grid, more: Grid, in_cell: bool) -> None:
    """``more``, a table's part on the next page, appended to ``grid``: its rows after ``grid``'s; with ``in_cell`` (the
    page goes on in the middle of a cell, the header repeating the row up to it) its top row goes on with ``grid``'s
    last, column by column: a cell's text after the text of the last row's cell in its column, a cell in a column the
    last row does not fill added to that row."""
    rows = sorted({c.start_row for c in more.cells})
    if in_cell and grid.cells and rows:
        top, last = rows[0], max(c.start_row for c in grid.cells)
        by_col = {c.start_col: c for c in grid.cells if c.start_row == last}
        for c in sorted((c for c in more.cells if c.start_row == top), key=lambda c: c.start_col):
            prev = by_col.get(c.start_col)
            if prev is None:
                grid.cells.append(c.model_copy(update={"start_row": last, "end_row": last + c.end_row - c.start_row}))
            elif c.text:
                join = "\n" if "\n" in prev.text or "\n" in c.text else " "
                text = prev.text + join + c.text
                lead, at = len(text) - len(text.lstrip()), len(prev.text) + len(join)
                prev.formulas = [[a - lead, e - lead] for a, e in prev.formulas] + \
                                [[a + at - lead, e + at - lead] for a, e in c.formulas]
                prev.text = text.strip()
        shift = last - top                    # the top row went into the last; the next rows follow it
        more_cells = [c for c in more.cells if c.start_row != top]
    else:
        shift = grid.num_rows - (rows[0] if rows else 0)
        more_cells = list(more.cells)
    for c in more_cells:
        grid.cells.append(c.model_copy(update={"start_row": c.start_row + shift, "end_row": c.end_row + shift}))
    grid.num_rows = max([grid.num_rows, *(c.end_row for c in grid.cells)])
    grid.num_cols = max([grid.num_cols, *(c.end_col for c in grid.cells)])
    grid.cells.sort(key=lambda c: (c.start_row, c.start_col))


def _grid(table: Table, fill_holes: bool = False) -> Grid:
    """A table's grid: its cells by position; ``fill_holes``: an empty cell at every position no cell covers."""
    cells = [c.model_copy() for c in table.cells]
    if fill_holes:
        covered = {(r, c) for x in table.cells for r in range(x.start_row, x.end_row)
                   for c in range(x.start_col, x.end_col)}
        cells += [Cell(start_row=r, end_row=r + 1, start_col=c, end_col=c + 1) for r in range(table.num_rows)
                  for c in range(table.num_cols) if (r, c) not in covered]
    cells.sort(key=lambda c: (c.start_row, c.start_col))
    return Grid(num_rows=table.num_rows, num_cols=table.num_cols, cells=cells)


def _region_link(t: Transcription, region: str, kind: str) -> str | None:
    """The reference a region's latest ``kind`` link (``runs_into``, ``continues``) names."""
    return next((ln.target for ln in reversed(t.links) if ln.source == region and ln.kind == kind), None)


class _PageContext:
    """The page being added: its number, its key for references (its id), its transcription and lines by id, its
    paragraphs (its latest recomposition's) and whether it has any, and the layer of the region being added."""

    def __init__(self, page_no: int, key: str, t: Transcription):
        self.page_no, self.key, self.t = page_no, key, t
        self.lines = {ln.id: ln for ln in t.lines}
        self.paragraphs = paragraphs_of(t)
        self.recomposed = bool(self.paragraphs)
        self.layer = "body"


def build_document(t: Transcription, name: str = "page", width: int | None = None, height: int | None = None,
                   sections: bool = False, policy: RenderingPolicy = DEFAULT_POLICY) -> Document:
    """The ``Document`` of one page (``DocumentBuilder`` with one page)."""
    b = DocumentBuilder(name, sections=sections, policy=policy)
    b.add_page(t, width, height)
    return b.build()
