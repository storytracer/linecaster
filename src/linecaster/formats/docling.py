"""DoclingDocuments read into transcriptions (``from_docling``: the importer ``import.docling.v1``), with the
``docling`` extra (docling-core). linecaster's own document is ``linecaster.document``; nothing else in linecaster
needs Docling."""
from __future__ import annotations

from ..data.transcription import Cell, Table, Transcription


def require_docling() -> None:
    """docling-core, or an ``ImportError`` that names the extra that installs it."""
    try:
        import docling_core  # noqa: F401
    except ImportError as e:
        raise ImportError("reading DoclingDocuments and DocTags needs docling-core: install linecaster[docling]") from e


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
    require_docling()
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
