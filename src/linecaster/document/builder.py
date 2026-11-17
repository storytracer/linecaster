"""``DocumentBuilder``: a page's or an item's transcriptions as one ``Document`` (``linecaster.document.model``).

The document is a rendering of the annotation sets, made again whenever it is needed (never stored with them). A
**rendering policy** (``linecaster.data.policy``, ``DEFAULT_POLICY`` by default) puts each region in a layer by its
content role, production and status: page headers, footers and page numbers in the **furniture** layer (the
serializers choose whether to include it), regions in ``none`` (removed, suppressed, duplicate, separators) and
``metadata`` left out, and lines it puts in ``none`` (a line assignment's duplicates). What an annotator wrote about
a zone (a description) is left out too, unless the policy puts it in a rendered layer (``page-layers-described``):
then it is a ``paragraph`` block with the role ``description`` after its region's block (the page's after the last).

The document is **literal**: a block's text is its lines' readings as the source or engine gave them, nothing
normalized or joined (``linecaster.document.strategy`` writes a strategy's document from it). Each line's formatting,
languages, inline formulas and the source's own edits (a correction, a word divided across lines or pages, an
expansion) are spans of the text; a drop capital (a region ``part_of`` the line it begins) is written at that line's
start.

**Without paragraphs**: one block per region, in reading order (regions without an order last, in list order), its
text one visual row per line (the region's lines on the same row joined with a space, rows joined with ``\\n``), one
origin with the region's box. A text region that continues another (its own ``continues`` link: a transcription
whose regions are its paragraphs, such as an imported ground truth) is appended to that one's block on a new row,
which is a wrap (``Block.wraps``) unless either part has several rows (verse, a stanza across a page break) and the
first does not end in a division mark (a word that goes on is a wrap in verse too).

**With paragraphs** (a recomposition ran: its latest recomposition's, ``linecaster.text.recomposition.paragraphs``):
one block per paragraph of a text region, its rows on rows of the text, every break between them a wrap, an origin
per row (its box and character span), a paragraph that continues another (its ``continues`` link by the same
annotator, in an earlier region or on an earlier page) appended to that one's block on a new row, a wrap. The
recomposition decides where paragraphs break and run on; the strategy what joins them.

The block's kind comes from the region's content role (``block_kind``): a title, a heading at the region's heading
level (1 when unset), a paragraph, list item, caption, note, page header or footer; a region with a table structure
(``Transcription.table``) a table by the policy's table rules (``TableRules``: one cell as text, one column as lines,
a one-row table after a table of its width that table's next row, holes filled); one with a formula
(``Transcription.formula``) a formula, its LaTeX the text; any other region (picture, chart, a table without a
structure) a picture, with the text read inside it and the image its source names (a ``<engine>__src`` extension).
Empty regions make no block.

``sections``: every title or heading opens a section that holds it and every block after it up to the next one,
across pages (``Block.section``); blocks before the first stay outside.

Writing: only what the transcriptions record (``Transcription.language``, ``.direction``), never an inferred value.
The document's language and direction are its pages' (their ``""`` classifications) where every page records the
same one; a block's are its region's (as resolved: the region's own, else what encloses it) where they differ from
the document's; a span's language and direction are a ``language`` and ``direction`` classification of a span of a
line.
"""
from __future__ import annotations

from linecaster.data.geometry import BBox
from linecaster.data.policy import DEFAULT_POLICY, RenderingPolicy
from linecaster.data.refs import parse
from linecaster.data.transcription import Cell, Line, Region, Table, Transcription
from linecaster.formats._xml import heading_level, hidden_line
from linecaster.text.recomposition import continuation, ends_with_mark, paragraphs as paragraphs_of
from linecaster.text.typography import line_bbox, zone_bbox
from linecaster.document.model import Block, Document, Grid, Origin, Page, Span

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
        self.doc = Document(name=name, strategy="literal")
        self.sections, self.policy = sections, policy
        self._section: str | None = None          # the heading block whose section is open
        self._last_table: Block | None = None      # the table a one-row table may join (merge_single_rows)
        self._items: dict[tuple[str, str], Block] = {}     # (page key, id) -> the block it continues
        self._pages_writing: list[tuple[str | None, str | None]] = []     # each page's language and direction
        self._writing: dict[str, tuple[str | None, str | None]] = {}      # block id -> its region's
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
        self._pages_writing.append((t.language(""), t.direction("")))
        paragraphs: dict[str | None, list] = {}
        for p in page.paragraphs:
            paragraphs.setdefault(p.region, []).append(p)
        described = self.policy.described(t)
        for r in t.ordered_regions():
            layer = self.policy.layer_of(t, r.id)
            if layer not in NOT_RENDERED:
                page.layer, page.region = layer, r.id
                self._add_region(page, r, by_region.get(r.id, []), paragraphs.get(r.id) if page.recomposed else None)
            self._add_descriptions(page, r, described.pop(r.id, ()))
        if None in paragraphs and not t.regions:          # a text-only page: its paragraphs without a region
            page.layer, page.region = "body", None
            self._add_paragraphs(page, None, "paragraph", paragraphs[None])
        self._add_descriptions(page, None, described.pop(None, ()))
        return page_no

    def _add_descriptions(self, page: "_PageContext", r: Region | None, descriptions) -> None:
        """A region's descriptions the policy renders, each a ``paragraph`` block with the role ``description``."""
        for layer, text in descriptions:
            if layer in NOT_RENDERED:
                continue
            page.layer, page.region = layer, r.id if r is not None else None
            self._last_table = None
            self._block("paragraph", page, text, role="description",
                        origins=[Origin(page=page.page_no, region=r.id if r is not None else None, lines=[],
                                        box=_box(_zone_box(r)) if r is not None else None, span=[0, len(text)])])

    def build(self) -> Document:
        """The document, every origin's box clamped to its page (a layout box often reaches a few pixels past the
        edge); the transcriptions keep their boxes. Its language and direction are the pages' where all record the
        same one, a block's its region's where they differ from the document's."""
        from linecaster.data.transcription import producer

        self.doc.producer = producer()
        for k, field in enumerate(("language", "direction")):
            values = {w[k] for w in self._pages_writing}
            setattr(self.doc, field, values.pop() if len(values) == 1 else None)
            for block in self.doc.blocks:
                value = self._writing.get(block.id, (None, None))[k]
                setattr(block, field, value if value != getattr(self.doc, field) else None)
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
        self._writing[b.id] = (page.t.language(page.region or ""), page.t.direction(page.region or ""))
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
        if _drop_capital_of(t, r.id) is not None:
            return                                  # written at the start of the line it begins
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
            block = continued
            # verse goes on with a row of its own; a part that ends in a division mark goes on with its word: a wrap
            wrap = ("\n" not in block.text and "\n" not in text) or ends_with_mark(block.text)
            offset = _append_row(block, text, spans, wrap)
            origin.span = [offset, len(block.text)]
            block.origins.append(origin)
        else:
            block = self._block(kind, page, text, role=role, level=level, spans=spans, origins=[origin])
        runs_into = _region_link(t, r.id, "runs_into")
        if runs_into is not None:
            ref = parse(runs_into)
            self._items[(ref.page or page.key, ref.id)] = block

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
        if continued is not None and continued.grid is not None:          # a table the previous page began
            block = continued
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
            self._items[(ref.page or page.key, ref.id)] = block

    def _add_paragraphs(self, page: "_PageContext", r: Region | None, kind: str, paragraphs: list,
                        level: int | None = None) -> None:
        """A text region's paragraphs: one block each, its rows on rows of the text (every break a wrap); a region of
        one paragraph without a letter (a page number) a block of its kind that opens no section; a paragraph that
        continues another appended to that one's block on a new row (a wrap)."""
        t = page.t
        role = t.role(r.id) if r is not None else None
        texts = [_paragraph_text(t, p, page.lines) for p in paragraphs]
        standalone = len(paragraphs) == 1 and not any(ch.isalpha() for ch in texts[0][0])
        for p, (text, spans, rows) in zip(paragraphs, texts):
            continues = continuation(t, p, "continues")
            continued = None if standalone or continues is None else self._items.get((page.key, p.id))
            wraps = [rows[k][1] for k in range(len(rows) - 1)]          # every row's end but the last
            if continued is not None:
                block = continued
                offset = _append_row(block, text, spans, True)
                block.wraps += [w + offset for w in wraps]
                block.origins.extend(self._row_origins(page, r, p, rows, offset))
            else:
                block = self._block(kind, page, text, opens=not standalone, role=role, level=level, spans=spans,
                                    wraps=wraps, origins=self._row_origins(page, r, p, rows))
            runs_into = continuation(t, p, "runs_into")
            if runs_into is not None:
                ref = parse(runs_into)
                self._items[(ref.page or page.key, ref.id)] = block

    def _row_origins(self, page: "_PageContext", r: Region | None, p, rows: list[tuple[int, int]],
                     offset: int = 0) -> list[Origin]:
        """One origin per row of paragraph ``p`` that has a box, its character span (``rows``) shifted by
        ``offset``."""
        out = []
        for row, (start, end) in zip(p.rows, rows):
            b = paragraph_box(row, page.lines)
            if b is None:
                continue
            out.append(Origin(page=page.page_no, region=r.id if r is not None else None, lines=list(row.lines),
                              box=_box(b), span=[start + offset, end + offset]))
        if not out and r is not None:            # text-only rows: the region's box
            end = rows[-1][1] if rows else 0
            out.append(Origin(page=page.page_no, region=r.id, box=_box(_zone_box(r)), span=[offset, offset + end]))
        return out


def paragraph_box(row, lines_by_id: dict[str, Line]) -> BBox | None:
    """The box of one row of a paragraph (``ParagraphRow``): the union of its lines' boxes (``line_bbox``), as
    ``region_rows`` makes it; None without geometry."""
    lines = [lines_by_id[i] for i in row.lines if i in lines_by_id]
    if not lines or not all(ln.polygon or ln.box for ln in lines):
        return None
    boxes = [line_bbox(ln) for ln in lines]
    return BBox(min(x.x0 for x in boxes), min(x.y0 for x in boxes), max(x.x1 for x in boxes), max(x.y1 for x in boxes))


def _append_row(block: Block, text: str, spans: list[Span], wrap: bool) -> int:
    """``text`` (with its ``spans``) appended to ``block`` on a new row, the break a wrap when ``wrap``; returns
    where it starts."""
    if wrap:
        block.wraps.append(len(block.text))
    offset = len(block.text) + 1
    block.text = block.text + "\n" + text
    block.spans += [s.model_copy(update={"start": s.start + offset, "end": s.end + offset}) for s in spans]
    return offset


def _drop_capital_of(t: Transcription, region: str) -> str | None:
    """The line a drop capital's region begins (its ``part_of`` link to a line), or None."""
    return next((ln.target for ln in reversed(t.links) if ln.kind == "part_of" and ln.source == region
                 and t.line(ln.target) is not None), None)


def _paragraph_text(t: Transcription, p, lines: dict[str, Line]) -> tuple[str, list[Span], list[tuple[int, int]]]:
    """A recomposed paragraph's literal text (``_rows_text`` of its rows), its spans and its rows' spans."""
    return _rows_text(t, [[lines[i] for i in row.lines if i in lines] for row in p.rows])


def _region_text(t: Transcription, lines: list[Line]) -> tuple[str, list[Span]]:
    """A region's literal text, one visual row per line (lines on a row joined with a space, rows with ``\\n``), and
    its spans (``_rows_text``). Consecutive lines share a row when the order gives them the same one and their boxes
    overlap vertically (``_side_by_side``): an order that gives no rows (every line row 0) or a line without geometry
    leaves each line a row of its own."""
    rows = t.rows()
    grouped: list[list[Line]] = []
    for ln in lines:
        prev = grouped[-1][-1] if grouped else None
        if (prev is not None and ln.id in rows and rows.get(prev.id) == rows[ln.id]
                and _side_by_side(prev, ln)):
            grouped[-1].append(ln)
        else:
            grouped.append([ln])
    text, spans, _ = _rows_text(t, grouped)
    return text, spans


def _side_by_side(a: Line, b: Line) -> bool:
    """Two lines on one visual row: their boxes overlap vertically by half the lower one's height."""
    if not (a.polygon or a.box) or not (b.polygon or b.box):
        return False
    x, y = line_bbox(a), line_bbox(b)
    overlap = min(x.y1, y.y1) - max(x.y0, y.y0)
    return overlap > 0.5 * min(x.y1 - x.y0, y.y1 - y.y0)


def _rows_text(t: Transcription, rows: list[list[Line]]) -> tuple[str, list[Span], list[tuple[int, int]]]:
    """Rows of lines as literal text (each line's reading; lines on a row joined with a space, rows with ``\\n``; a
    drop capital's text at the start of the line it begins), each row's span of it, and the lines' formatting,
    languages, writing directions, inline formulas (``Transcription.formulas`` on a span of a line) and the source's edits of spans
    (``Transcription.edits``: corrected, joined, expanded, regularized) as spans."""
    drops: dict[str, str] = {}
    for ln in t.links:
        if ln.kind == "part_of" and t.line(ln.target) is not None and t.region(ln.source) is not None:
            letters = "".join(t.text_of(x) or "" for x in t.lines if t.region_of(x) == ln.source).strip()
            if letters:
                drops[ln.target] = letters
    edits: dict[str, list[tuple[int, int, str, str]]] = {}
    for e in t.edits:
        if "[" in str(e.target):
            p = parse(str(e.target))
            if p.span is not None:
                edits.setdefault(p.id, []).append((p.span[0], p.span[1], e.kind, e.text))
        elif "/" not in str(e.target) and "#" not in str(e.target):         # a whole line's edit: all its text
            line = t.line(str(e.target))
            if line is not None:
                edits.setdefault(line.id, []).append((0, len(t.text_of(line) or ""), e.kind, e.text))
    languages: dict[str, list[tuple[int, int, str]]] = {}
    directions: dict[str, list[tuple[int, int, str]]] = {}
    for c in t.classifications:
        if c.scheme in ("language", "direction") and "[" in str(c.target):
            p = parse(str(c.target))
            if p.span is not None:
                (languages if c.scheme == "language" else directions).setdefault(p.id, []).append(
                    (p.span[0], p.span[1], str(c.value)))
    formulas: dict[str, list[tuple[int, int]]] = {}
    for f in t.formulas:
        if "[" in str(f.target):
            p = parse(str(f.target))
            if p.span is not None:
                formulas.setdefault(p.id, []).append(p.span)
    text, spans, row_spans = "", [], []
    for k, row_lines in enumerate(rows):
        start = len(text) + (1 if k else 0)
        parts = []
        for ln in row_lines:
            x = t.text_of(ln)
            if not x:
                continue
            drop = drops.get(ln.id, "")
            at = start + sum(len(s) + 1 for s in parts) + len(drop)
            for f in (ln.reading.formatting if ln.reading is not None else []):
                a, e = f.charspan or (0, len(x))
                if e > a and (f.bold or f.italic or f.underline or f.strikethrough or f.script != "baseline"):
                    spans.append(Span(start=at + a, end=at + e, bold=f.bold, italic=f.italic, underline=f.underline,
                                      strikethrough=f.strikethrough, script=f.script))
            for a, e, lang in languages.get(ln.id, []):
                if e > a:
                    spans.append(Span(start=at + a, end=at + e, language=lang))
            for a, e, direction in directions.get(ln.id, []):
                if e > a:
                    spans.append(Span(start=at + a, end=at + e, direction=direction))
            for a, e in formulas.get(ln.id, []):
                if e > a:
                    spans.append(Span(start=at + a, end=at + e, formula=True))
            for a, e, kind, edit_text in edits.get(ln.id, []):
                if e >= a:
                    spans.append(Span(start=at + a, end=at + e, edit=kind, edit_text=edit_text))
            parts.append(drop + x if not drop else drop + x.lstrip())
        row = " ".join(parts)                  # a row of empty lines stays, as an empty row
        text += ("\n" if k else "") + row
        row_spans.append((start, len(text)))
    return text, spans, row_spans


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
    paragraphs (its latest recomposition's) and whether it has any, and the layer and id of the region being added."""

    def __init__(self, page_no: int, key: str, t: Transcription):
        self.page_no, self.key, self.t = page_no, key, t
        self.lines = {ln.id: ln for ln in t.lines}
        self.paragraphs = paragraphs_of(t)
        self.recomposed = bool(self.paragraphs)
        self.layer = "body"
        self.region: str | None = None


def build_document(t: Transcription, name: str = "page", width: int | None = None, height: int | None = None,
                   sections: bool = False, policy: RenderingPolicy = DEFAULT_POLICY) -> Document:
    """The ``Document`` of one page (``DocumentBuilder`` with one page)."""
    b = DocumentBuilder(name, sections=sections, policy=policy)
    b.add_page(t, width, height)
    return b.build()
