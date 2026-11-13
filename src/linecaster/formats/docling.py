"""Page and item composition: a ``Transcription`` rendered as a ``DoclingDocument`` (``build_docling``,
``DocumentBuilder``; the ``Composer``), an item's pages composed into one (``Composer(unit="item")``), and the
Markdown and text exports of them.

The document is a rendering of the annotation set, made again whenever it is needed (never stored with the set). A
**rendering policy** (``linecaster.data.policy``, ``DEFAULT_POLICY`` by default) puts each region in a content layer
by its content role, production and status: regions in docling-core's layers become items there (page headers,
page footers and page numbers in the **furniture** layer: the exports choose whether to include it,
``furniture=True``), regions in ``none`` (removed, suppressed, duplicate, separators) and ``metadata`` are left out
(and lines it puts in ``none``, a line assignment's duplicates), and descriptions (``Description``) are never
text.

Without paragraphs (diplomatic composition): one Docling item per region, in reading order (regions
without an order last, in list order), its text one visual row per line (the region's lines on the same row
joined with a space, rows joined with ``\\n``; each line's text as written, its ``nfc`` and ``joined`` edits applied:
``linecaster.text.recomposition.region_rows``), one provenance entry with the region's box. Its Docling label
(``Transcription.label``, from its content role) decides the item:

- ``title`` -> title, ``section_header`` -> heading at the region's heading level (1 when unset;
  ``linecaster.formats._xml.heading_level``),
  ``text``/``caption``/``footnote``/``list_item``/``page_header``/... -> text items with Docling's label;
- a region with a table structure (``Transcription.table``) -> a table item (``table_data``: cells with text,
  spans, header flags and box); with a formula (``Transcription.formula``, LaTeX) -> a formula item;
- any other region (picture, chart, a table without a structure) -> a picture, with the text read
  inside it as a child text item.

Empty regions produce no item. ``build_docling`` makes the document of one page (page 1);
``DocumentBuilder`` binds all pages of an item into one, with paragraphs continued across page breaks,
optional sections and the region map for Markdown dividers. Exports (``export``): Markdown, text, HTML, DocLang and
JSON, all docling-core's own serializers.

With paragraphs (a recomposition ran; ``linecaster.engines.recomposition``; the latest recomposition's count): one
item per paragraph of a text region with a provenance entry per row, and a paragraph that continues another (its
``continues`` link, a reference ``<id>`` or ``<page_id>#<id>``: in an earlier region, or on an earlier page of the
item) appended to that one's item. The recomposition decides; the builder only
composes.
"""
from __future__ import annotations

from typing import Any

from ..data.geometry import BBox
from ..data.policy import DEFAULT_POLICY, RenderingPolicy
from ..data.refs import parse
from ..data.transcription import Cell, Line, Region, Table, Transcription
from ..text.recomposition import continuation, paragraphs as paragraphs_of, region_rows
from ..text.typography import line_bbox, zone_bbox
from ._xml import heading_level, hidden_line

TEXT_LABELS = {
    "text": "text", "paragraph": "text", "title": "title", "section_header": "section_header",
    "caption": "caption", "footnote": "footnote", "page_header": "page_header", "page_footer": "page_footer",
    "list_item": "list_item", "formula": "formula", "code": "code", "reference": "reference",
    "document_index": "document_index",
}
#: the layers a rendering policy has besides docling-core's (``ContentLayer``): what is not rendered as items
NOT_RENDERED = ("metadata", "none")
#: the ``Document.metadata`` keys of a composed page or item (``Composer``): the DoclingDocument (as a dict), the
#: map of its items to ``"<page_no>:<region id>"`` (the Markdown dividers), and, for a page, the transcription it
#: was composed from
DOCUMENT_KEY, REGION_MAP_KEY, COMPOSED_KEY = "docling", "region_of", "docling_transcription"


def region_text(t: Transcription, lines: list[Line]) -> str:
    """One visual row per line: the lines on the same row joined with a space, in row order (``region_rows``)."""
    return "\n".join(row.text for row in region_rows(t, lines))


def _box(b: BBox):
    from docling_core.types.doc import BoundingBox, CoordOrigin

    return BoundingBox(l=b.x0, t=b.y0, r=b.x1, b=b.y1, coord_origin=CoordOrigin.TOPLEFT)


def _prov(b: BBox, text: str = "", page_no: int = 1):
    from docling_core.types.doc import ProvenanceItem

    return ProvenanceItem(page_no=page_no, bbox=_box(b), charspan=(0, len(text)))


def table_data(table: Table):
    """A table structure as docling-core's ``TableData``: its cells (text, offsets, spans, header and section flags,
    box) and size. ``from_table_data`` reads it back."""
    from docling_core.types.doc import TableCell, TableData

    cells = []
    for c in table.cells:
        b = BBox(c.box[0], c.box[1], c.box[0] + c.box[2], c.box[1] + c.box[3]) if c.box else None
        cells.append(TableCell(text=c.text, start_row_offset_idx=c.start_row, end_row_offset_idx=c.end_row,
                               start_col_offset_idx=c.start_col, end_col_offset_idx=c.end_col, row_span=c.row_span,
                               col_span=c.col_span, column_header=c.column_header, row_header=c.row_header,
                               row_section=c.row_section, bbox=_box(b) if b else None))
    return TableData(table_cells=cells, num_rows=table.num_rows, num_cols=table.num_cols)


def from_table_data(data, annotator: int, target: str, page_height: float | None = None, **fields) -> Table:
    """A ``Table`` of region ``target`` by ``annotator`` from docling-core's ``TableData`` (``table_data``'s
    inverse); a cell's box from its ``bbox`` (one with a bottom-left origin needs ``page_height``). ``fields``
    are further ``Table`` fields (``html``, ``output``, ...)."""
    from docling_core.types.doc import CoordOrigin

    cells = []
    for c in data.table_cells:
        box = None
        if c.bbox is not None:
            b = c.bbox
            if b.coord_origin != CoordOrigin.TOPLEFT:
                if page_height is None:
                    raise ValueError("a cell box with a bottom-left origin needs the page height")
                b = b.to_top_left_origin(page_height)
            box = [b.l, b.t, b.r - b.l, b.b - b.t]
        cells.append(Cell(start_row=c.start_row_offset_idx, end_row=c.end_row_offset_idx,
                          start_col=c.start_col_offset_idx, end_col=c.end_col_offset_idx, text=c.text, box=box,
                          column_header=c.column_header, row_header=c.row_header, row_section=c.row_section))
    return Table(annotator=annotator, target=target, num_rows=data.num_rows, num_cols=data.num_cols, cells=cells,
                 **fields)


def paragraph_box(row, lines_by_id: dict[str, Line]) -> BBox | None:
    """The box of one row of a paragraph (``ParagraphRow``): the union of its lines' boxes (``line_bbox``), as
    ``region_rows`` makes it; None without geometry."""
    lines = [lines_by_id[i] for i in row.lines if i in lines_by_id]
    if not lines or not all(ln.polygon or ln.box for ln in lines):
        return None
    boxes = [line_bbox(ln) for ln in lines]
    return BBox(min(x.x0 for x in boxes), min(x.y0 for x in boxes), max(x.x1 for x in boxes), max(x.y1 for x in boxes))


class DocumentBuilder:
    """One ``DoclingDocument`` for one page or for all pages of an item, in order (``add_page`` once per
    page). Page ``n`` of the document is the ``n``-th page added
    (``page_no`` in every provenance entry).

    A page's text regions are composed from its **paragraphs** when it has them (a recomposition ran: its latest
    recomposition's, ``linecaster.text.recomposition.paragraphs``): one item per paragraph with a provenance entry
    per row (its box and character span), a paragraph that continues another (its ``continues`` link by the same
    annotator, in an earlier region or on an earlier page) appended to that one's item. Without paragraphs (diplomatic composition) one
    item per region, its text one visual row per line, one provenance entry with the region's box.

    ``policy`` (the rendering policy) puts each region in its content layer; regions it puts in ``none`` or
    ``metadata`` are left out.

    ``sections``: every heading (title or section header) opens a Docling ``section`` group, named after
    it, that holds it and everything after it up to the next heading, across pages; items before the
    first heading stay in the body. Markdown and text read the same; JSON gains the tree. A title opens its
    section the same way with and without paragraphs: the group first, the title inside.

    ``region_of`` maps each item's ``self_ref`` to ``"<page_no>:<region id>"``, for the Markdown
    dividers (``to_markdown(..., region_of=...)``)."""

    def __init__(self, name: str = "document", sections: bool = False, policy: RenderingPolicy = DEFAULT_POLICY):
        from docling_core.types.doc import DoclingDocument

        self.doc = DoclingDocument(name=name)
        self.sections, self.policy = sections, policy
        self._section = None      # the open section GroupItem, or None for the body
        self._level = 1
        self._items: dict[tuple[str, str], Any] = {}     # (page key, paragraph id) -> the item it is in
        self.pages = 0
        self.region_of: dict[str, str] = {}

    # ------------------------------------------------------------------ pages
    def add_page(self, t: Transcription, width: int | None = None, height: int | None = None,
                 page_no: int | None = None, page_id: str | None = None) -> int:
        """Add one page; ``page_id`` names it for paragraphs continued from it (``<page_id>#<paragraph id>``
        references)."""
        from docling_core.types.doc import Size

        self.pages += 1
        page_no = page_no or self.pages
        w, h = width or t.source.image_width, height or t.source.image_height
        if w and h:
            self.doc.add_page(page_no=page_no, size=Size(width=w, height=h))
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
            before = (len(self.doc.texts), len(self.doc.pictures), len(self.doc.tables))
            self._add_region(page, r, by_region.get(r.id, []), paragraphs.get(r.id) if page.recomposed else None)
            key = f"{page_no}:{r.id}"
            for items, n in zip((self.doc.texts, self.doc.pictures, self.doc.tables), before):
                for it in items[n:]:
                    self.region_of[it.self_ref] = key
        if None in paragraphs and not t.regions:          # a text-only page: its paragraphs without a region
            page.layer = "body"
            self._add_paragraphs(page, None, "text", paragraphs[None])
        return page_no

    def build(self):
        """The document, validated by docling-core (``validate_document``: a consistent tree, and every
        provenance box clamped to its page, as docling-core does whenever it validates a document, e.g. on
        loading; its out-of-bounds warnings are silenced, layout boxes often reach a few pixels past the edge)."""
        import warnings

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*outside page bounds.*", category=UserWarning)
            self.doc.validate_document()
        return self.doc

    # ---------------------------------------------------------------- regions
    def _add_region(self, page: "_PageContext", r: Region, lines: list[Line], paragraphs: list | None) -> None:
        from docling_core.types.doc import DocItemLabel

        t, page_no, layer = page.t, page.page_no, page.content_layer
        b = zone_bbox(r)
        label = t.label(r.id)
        self._level = heading_level(t, r.id) or 1
        f, table = t.formula(r.id), t.table(r.id)
        formula = f.latex if f is not None else None
        if paragraphs is not None and formula is None and table is None and label in TEXT_LABELS:
            self._add_paragraphs(page, r, TEXT_LABELS[label], paragraphs)
            return
        if page.recomposed and formula is None and table is None and label in TEXT_LABELS:
            return                    # recomposed, no paragraphs: the region has no text
        content = region_text(t, lines)
        if formula is not None:
            if formula.strip():
                self.doc.add_text(label=DocItemLabel.FORMULA, text=formula, prov=_prov(b, formula, page_no),
                                  parent=self._section, content_layer=layer)
        elif table is not None:
            self.doc.add_table(data=table_data(table), prov=_prov(b, "", page_no), parent=self._section,
                               content_layer=layer)
        elif label in TEXT_LABELS:
            if content.strip():
                self._add_text(DocItemLabel(TEXT_LABELS[label]), content, _prov(b, content, page_no), layer)
        else:
            pic = self.doc.add_picture(prov=_prov(b, "", page_no), parent=self._section, content_layer=layer)
            if content.strip():
                self.doc.add_text(label=DocItemLabel.TEXT, text=content, prov=_prov(b, content, page_no), parent=pic,
                                  content_layer=layer)

    def _open_section(self, text: str) -> None:
        from docling_core.types.doc import GroupLabel

        if self.sections:
            self._section = self.doc.add_group(label=GroupLabel.SECTION, name=" ".join(text.split())[:80])

    def _add_text(self, label, text: str, prov, layer=None):
        from docling_core.types.doc import DocItemLabel

        if label in (DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER):
            self._open_section(text)
        if label == DocItemLabel.TITLE:
            return self.doc.add_title(text=text, prov=prov, parent=self._section, content_layer=layer)
        if label == DocItemLabel.SECTION_HEADER:
            return self.doc.add_heading(text=text, prov=prov, parent=self._section, level=self._level,
                                        content_layer=layer)
        return self.doc.add_text(label=label, text=text, prov=prov, parent=self._section, content_layer=layer)

    def _add_paragraphs(self, page: "_PageContext", r: Region | None, label_name: str, paragraphs: list) -> None:
        """A text region's paragraphs: one item each (headings through ``_add_text``, so they open their
        sections); a region of one paragraph without a letter (a page number) as a plain item of its label; a
        paragraph that continues another appended to that one's item, its rows' character spans after the text
        before it."""
        from docling_core.types.doc import DocItemLabel

        t, layer = page.t, page.content_layer
        label = DocItemLabel(label_name)
        single = label in (DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER)
        standalone = len(paragraphs) == 1 and not any(ch.isalpha() for ch in paragraphs[0].text)
        for p in paragraphs:
            provs = self._row_provs(page, r, p)
            continues = continuation(t, p, "continues")
            continued = None if standalone or continues is None else self._items.get((page.key, p.id))
            if continued is not None:
                item, sep = continued
                joined = item.text + sep + p.text
                offset = len(joined) - len(p.text)
                item.text = item.orig = joined
                item.prov.extend(self._row_provs(page, r, p, offset))
            elif standalone or not single:
                item = self.doc.add_text(label=label, text=p.text, prov=provs[0] if provs else None,
                                         parent=self._section, content_layer=layer)
                item.prov.extend(provs[1:])
            else:
                item = self._add_text(label, p.text, provs[0] if provs else None, layer)
                item.prov.extend(provs[1:])
            runs_into = continuation(t, p, "runs_into")
            if runs_into is not None:
                ref = parse(runs_into)
                sep = next((d.separator for d in reversed(p.decisions) if d.kind == "continuation"), None) or ""
                self._items[(ref.page or page.key, ref.id)] = (item, sep)

    def _row_provs(self, page: "_PageContext", r: Region | None, p, offset: int = 0) -> list:
        """One provenance entry per row of paragraph ``p`` that has a box, its character span shifted by
        ``offset``. A division mark removed at a continuation stays in its row's span (the row's span as
        recognized, the mark included), so the last row's span ends one character later then."""
        from docling_core.types.doc import ProvenanceItem

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
            out.append(ProvenanceItem(page_no=page.page_no, bbox=_box(b), charspan=(start + offset, end + offset)))
        if not out and r is not None:            # text-only rows: the region's box
            b = zone_bbox(r)
            out.append(ProvenanceItem(page_no=page.page_no, bbox=_box(b), charspan=(offset, offset + len(p.text))))
        return out


class _PageContext:
    """The page being added: its number, its key for references (its id), its transcription and lines by id, its
    paragraphs (its latest recomposition's) and whether it has any, and the layer of the region being added."""

    def __init__(self, page_no: int, key: str, t: Transcription):
        self.page_no, self.key, self.t = page_no, key, t
        self.lines = {ln.id: ln for ln in t.lines}
        self.paragraphs = paragraphs_of(t)
        self.recomposed = bool(self.paragraphs)
        self.layer = "body"

    @property
    def content_layer(self):
        """docling-core's ``ContentLayer`` of the region being added (``None`` for the body, docling-core's
        default)."""
        from docling_core.types.doc import ContentLayer

        return None if self.layer == "body" else ContentLayer(self.layer)


def build_docling(t: Transcription, name: str = "page", width: int | None = None, height: int | None = None,
                  sections: bool = False, policy: RenderingPolicy = DEFAULT_POLICY):
    """The ``DoclingDocument`` of one page (``DocumentBuilder`` with one page)."""
    return compose(t, name, width, height, sections, policy)[0]


def compose(t: Transcription, name: str = "page", width: int | None = None, height: int | None = None,
            sections: bool = False, policy: RenderingPolicy = DEFAULT_POLICY) -> tuple[Any, dict[str, str]]:
    """The ``DoclingDocument`` of one page and the map of its items to ``"<page_no>:<region id>"``
    (``DocumentBuilder.region_of``, for the Markdown dividers)."""
    b = DocumentBuilder(name, sections=sections, policy=policy)
    b.add_page(t, width, height)
    return b.build(), dict(b.region_of)


def docling_dict(doc) -> dict[str, Any]:
    return doc.export_to_dict()


def load_docling(source):
    """A ``DoclingDocument``: a document as it is, a document dict validated (``doc.metadata["docling"]``, as the
    ``Composer`` puts it), a transcription rendered (``build_docling``)."""
    from docling_core.types.doc import DoclingDocument

    if isinstance(source, DoclingDocument):
        return source
    if isinstance(source, Transcription):
        return build_docling(source)
    return DoclingDocument.model_validate(source)


def _layers(furniture: bool):
    from docling_core.types.doc import ContentLayer

    return {ContentLayer.BODY, ContentLayer.FURNITURE} if furniture else {ContentLayer.BODY}


def _span_aware_table_serializer():
    """Docling's pipe table for a plain grid, its HTML table when a cell spans (the pipe table would repeat
    a spanning cell's text in every cell it covers)."""
    from docling_core.transforms.serializer.html import HTMLTableSerializer
    from docling_core.transforms.serializer.markdown import MarkdownTableSerializer

    class SpanAwareTableSerializer(MarkdownTableSerializer):
        def serialize(self, *, item, doc_serializer, doc, **kwargs):
            if any(c.row_span > 1 or c.col_span > 1 for c in item.data.table_cells):
                return HTMLTableSerializer().serialize(item=item, doc_serializer=doc_serializer, doc=doc, **kwargs)
            return super().serialize(item=item, doc_serializer=doc_serializer, doc=doc, **kwargs)

        def get_header_and_body_lines(self, *, table_text, **kwargs):
            if table_text.lstrip().startswith("<table"):
                return HTMLTableSerializer().get_header_and_body_lines(table_text=table_text, **kwargs)
            return super().get_header_and_body_lines(table_text=table_text, **kwargs)

    return SpanAwareTableSerializer()


def to_markdown(doc_or_t, furniture: bool = False, region_of: dict[str, str] | None = None) -> str:
    """Markdown with Docling's defaults, tables with spanning cells as HTML; page headers and footers
    only with ``furniture``. With ``region_of`` (``DocumentBuilder.region_of``) a ``---`` rule separates
    the items of one layout region from the next."""
    from docling_core.transforms.serializer.markdown import MarkdownDocSerializer, MarkdownParams
    from docling_core.types.doc import GroupItem

    doc = load_docling(doc_or_t)
    layers = _layers(furniture)
    ser = MarkdownDocSerializer(doc=doc, table_serializer=_span_aware_table_serializer(),
                                params=MarkdownParams(layers=layers))
    if not region_of:
        return ser.serialize().text
    blocks: list[str] = []
    last = None
    for item, _level in doc.iterate_items(included_content_layers=layers):
        if isinstance(item, GroupItem):
            continue
        text = ser.serialize(item=item).text
        if not text.strip():
            continue
        key = region_of.get(item.self_ref)
        if blocks and key != last:
            blocks.append("---")
        blocks.append(text)
        last = key
    return "\n\n".join(blocks)


def to_text(doc_or_t, furniture: bool = False) -> str:
    """Docling's plain-text export; page headers and footers only with ``furniture``."""
    doc = load_docling(doc_or_t)
    return doc.export_to_text(included_content_layers=_layers(furniture))


def to_html(doc_or_t, furniture: bool = False) -> str:
    """Docling's HTML export (its own defaults); page headers and footers only with ``furniture``."""
    doc = load_docling(doc_or_t)
    return doc.export_to_html(included_content_layers=_layers(furniture))


def to_doclang(doc_or_t) -> str:
    """Docling's DocLang XML, with named groups (sections survive as ``<group>``). DocLang keeps every
    content layer and marks the furniture items (``<layer value="furniture"/>``), so it has no
    ``furniture`` switch. docling-core's DocLang export rewrites the provenance charspans of the document it
    serializes, so it runs on a copy (0.3's JSON depended on whether doclang was exported before it)."""
    doc = load_docling(doc_or_t)
    return doc.model_copy(deep=True).export_to_doclang(add_named_groups=True)


def to_json(doc_or_dict) -> str:
    """The DoclingDocument as JSON, formatted as docling-core's ``save_as_json`` writes it (indent 2,
    ASCII-escaped)."""
    import json

    if isinstance(doc_or_dict, Transcription):
        doc_or_dict = build_docling(doc_or_dict)
    data = doc_or_dict if isinstance(doc_or_dict, dict) else docling_dict(doc_or_dict)
    return json.dumps(data, indent=2)


#: document export formats (``export``) -> file extension
EXPORT_FORMATS = {"md": "md", "txt": "txt", "html": "html", "doclang": "doclang.xml", "json": "json"}


def export(doc, fmt: str, furniture: bool = False, region_of: dict[str, str] | None = None) -> str:
    """One export of a ``DoclingDocument`` (a document dict, or a transcription, rendered: ``load_docling``): ``md``
    (``region_of`` puts ``---`` dividers between layout regions), ``txt``, ``html``, ``doclang`` or
    ``json``. ``furniture`` keeps page headers and footers in md, txt and html (json and doclang
    always hold them, in Docling's furniture layer)."""
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"unknown export format {fmt!r}; choose from {', '.join(EXPORT_FORMATS)}")
    if fmt == "json":
        return to_json(doc)
    doc = load_docling(doc)
    if fmt == "md":
        return to_markdown(doc, furniture, region_of)
    if fmt == "txt":
        return to_text(doc, furniture)
    if fmt == "html":
        return to_html(doc, furniture)
    return to_doclang(doc)



def from_docling(source, page_no: int | None = None, ground_truth: bool = False, name: str = "docling",
                 dataset: str | None = None, record: str | None = None) -> Transcription:
    """Reads a DoclingDocument (a document, its dict or its JSON) into a transcription: one region per item of
    the body, furniture and notes layers (on page ``page_no``, or every page), in the document's order, with
    the content role of its label and the box of its first provenance entry (top-left origin; ``None`` without
    one); a text item's text as one line per text line, a section header's level as ``heading_level``, a table as
    a ``Table`` (and one line with its cells' text, so it renders), a picture as a region without lines.

    One annotator: people (kind ``human``) with ``ground_truth``, which also sets ``source.kind`` to
    ``ground_truth``, else a file (kind ``file``), named ``name``. ``dataset`` and ``record`` go to the source.
    """
    from docling_core.types.doc import ContentLayer, CoordOrigin, DoclingDocument, SectionHeaderItem, TableItem

    from ..data.policy import classify_label
    from ..data.transcription import Annotator, Source

    if isinstance(source, str):
        doc = DoclingDocument.model_validate_json(source)
    elif isinstance(source, dict):
        doc = DoclingDocument.model_validate(source)
    else:
        doc = source
    size = doc.pages.get(page_no) if page_no is not None else (next(iter(doc.pages.values())) if doc.pages else None)
    width = int(size.size.width) if size is not None else None
    height = int(size.size.height) if size is not None else None
    t = Transcription(source=Source(kind="ground_truth" if ground_truth else "converted", format="docling",
                                    dataset=dataset, record=record, image_width=width, image_height=height))
    a = t.add_annotator(Annotator(kind="human" if ground_truth else "file", step="transcription", name=name))
    layers = {ContentLayer.BODY, ContentLayer.FURNITURE, ContentLayer.NOTES}
    order, lines = [], []
    for k, (item, _level) in enumerate(doc.iterate_items(with_groups=False, included_content_layers=layers)):
        prov = getattr(item, "prov", None) or []
        if page_no is not None and prov and prov[0].page_no != page_no:
            continue
        box = None
        if prov:
            b = prov[0].bbox
            page = doc.pages.get(prov[0].page_no)
            h = page.size.height if page is not None else height
            if b.coord_origin != CoordOrigin.TOPLEFT and h:
                b = b.to_top_left_origin(h)
            if b.coord_origin == CoordOrigin.TOPLEFT:
                box = [b.l, b.t, b.r - b.l, b.b - b.t]
        label = str(getattr(item.label, "value", item.label))
        rid = f"{label}_{k}"
        t.add_region(a, rid, box, label=label, role=label,
                     heading_level=item.level if isinstance(item, SectionHeaderItem) else None)
        order.append(rid)
        if isinstance(item, TableItem):
            page = doc.pages.get(prov[0].page_no) if prov else None
            t.tables.append(from_table_data(item.data, a, rid,
                                            page_height=page.size.height if page is not None else height))
            text = " ".join(c.text for c in item.data.table_cells if c.text)
            texts = [text] if text else []
        else:
            text = getattr(item, "text", "") or ""
            texts = text.split("\n") if text else []
        for j, s in enumerate(texts):
            lines.append(t.add_line(a, f"{rid}_l{j}", region=rid, text=s).id)
    t.add_order(a, order, lines)
    return t
