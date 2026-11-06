"""The DocumentBuilder as it was before the recomposition moved into its engine (linecaster 531a422, squiddleocr's
builder): it recomposed while it built (``text="reflow"``). Kept verbatim as the reference the recomposition engine
and the Composer are compared with (``test_recomposition_parity.py``)."""
from __future__ import annotations

from linecaster.data.geometry import bbox_of
from linecaster.data.transcription import Line, Region, Transcription
from linecaster.formats.docling import TEXT_LABELS, _box, _layer, _prov, _table_data, region_rows, region_text
from legacy_recomposition import ends_with_mark, resolve_mark, separator

TEXT_MODES = ("lines", "reflow")


class LegacyDocumentBuilder:
    """One ``DoclingDocument`` for one page or for all pages of an item, in order (squiddleocr's
    ``DocumentBuilder``; ``add_page`` once per page). Page ``n`` of the document is the ``n``-th page added
    (``page_no`` in every provenance entry).

    ``text``: ``lines`` or ``reflow`` (see the module docstring). In ``reflow`` mode the lexicon grows with
    every page added and a paragraph left open at the foot of a page continues on the next page (an
    item of digits only, a page number, between them does not close it).

    ``sections``: every heading (title or section header) opens a Docling ``section`` group, named after
    it, that holds it and everything after it up to the next heading, across pages; items before the
    first heading stay in the body. Markdown and text read the same; JSON gains the tree. (squiddleocr
    7c8a052 crashes on reflow + sections when a title appears; here a title opens its section the same
    way in both modes: the group first, the title inside.)

    ``region_of`` maps each item's ``self_ref`` to ``"<page_no>:<region id>"``, for the Markdown
    dividers (``to_markdown(..., region_of=...)``)."""

    def __init__(self, name: str = "document", text: str = "lines", sections: bool = False, rtl: bool = False,
                 stats=None):
        from docling_core.types.doc import DoclingDocument

        from legacy_recomposition import Lexicon, Stats

        if text not in TEXT_MODES:
            raise ValueError(f"unknown text mode {text!r}; choose {', '.join(TEXT_MODES)}")
        self.doc = DoclingDocument(name=name)
        self.text_mode, self.sections, self.rtl = text, sections, rtl
        self.lexicon, self.stats = Lexicon(), stats if stats is not None else Stats()
        self._section = None      # the open section GroupItem, or None for the body
        self._open = None         # (TextItem, Paragraph, Margins) of a paragraph that may continue
        self._level = 1
        self.pages = 0
        self.region_of: dict[str, str] = {}

    # ------------------------------------------------------------------ pages
    def add_page(self, t: Transcription, width: int | None = None, height: int | None = None,
                 page_no: int | None = None) -> int:
        from docling_core.types.doc import Size

        self.pages += 1
        page_no = page_no or self.pages
        w, h = width or t.source.image_width, height or t.source.image_height
        if w and h:
            self.doc.add_page(page_no=page_no, size=Size(width=w, height=h))
        by_region: dict[str, list[Line]] = {}
        for ln in t.lines:
            by_region.setdefault(ln.region_id, []).append(ln)
        regions = sorted(t.regions, key=lambda r: r.reading_order if r.reading_order is not None else 1 << 30)
        if self.text_mode == "reflow":
            for r in regions:
                self.lexicon.add(region_text(by_region.get(r.id, [])))
        for r in regions:
            before = (len(self.doc.texts), len(self.doc.pictures), len(self.doc.tables))
            self._add_region(page_no, r, by_region.get(r.id, []))
            key = f"{page_no}:{r.id}"
            for items, n in zip((self.doc.texts, self.doc.pictures, self.doc.tables), before):
                for it in items[n:]:
                    self.region_of[it.self_ref] = key
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
    def _add_region(self, page_no: int, r: Region, lines: list[Line]) -> None:
        from docling_core.types.doc import DocItemLabel

        b = bbox_of(r.polygon)
        self._level = r.heading_level or 1
        formula, table = r.extra.get("formula"), r.extra.get("table")
        if self.text_mode == "reflow" and formula is None and table is None and r.label in TEXT_LABELS:
            self._add_reflowed(page_no, r, region_rows(lines))
            return
        self._open = None
        content = region_text(lines)
        if formula is not None:
            if formula.strip():
                self.doc.add_text(label=DocItemLabel.FORMULA, text=formula, prov=_prov(b, formula, page_no),
                                  parent=self._section)
        elif table is not None:
            self.doc.add_table(data=_table_data(table), prov=_prov(b, "", page_no), parent=self._section)
        elif r.label in TEXT_LABELS:
            if content.strip():
                self._add_text(DocItemLabel(TEXT_LABELS[r.label]), content, _prov(b, content, page_no))
        else:
            pic = self.doc.add_picture(prov=_prov(b, "", page_no), parent=self._section)
            if content.strip():
                self.doc.add_text(label=DocItemLabel.TEXT, text=content, prov=_prov(b, content, page_no), parent=pic)

    def _open_section(self, text: str) -> None:
        from docling_core.types.doc import GroupLabel

        if self.sections:
            self._section = self.doc.add_group(label=GroupLabel.SECTION, name=" ".join(text.split())[:80])

    def _add_text(self, label, text: str, prov):
        from docling_core.types.doc import DocItemLabel

        if label in (DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER):
            self._open_section(text)
        if label == DocItemLabel.TITLE:
            return self.doc.add_title(text=text, prov=prov, parent=self._section)
        if label == DocItemLabel.SECTION_HEADER:
            return self.doc.add_heading(text=text, prov=prov, parent=self._section, level=self._level)
        return self.doc.add_text(label=label, text=text, prov=prov, parent=self._section, content_layer=_layer(label))

    def _add_reflowed(self, page_no: int, r: Region, rows) -> None:
        from docling_core.types.doc import DocItemLabel

        from legacy_recomposition import Margins, continues, reflow_rows

        label = DocItemLabel(TEXT_LABELS[r.label])
        single = label in (DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER)
        paragraphs = reflow_rows(rows, self.rtl, self.lexicon, single, self.stats)
        if not paragraphs:
            return
        m = Margins.of([row for row in rows if row.text.strip()], self.rtl)
        if len(paragraphs) == 1 and not any(ch.isalpha() for ch in paragraphs[0].text):
            # furniture (a page number, whatever the layout called it): added; an open paragraph stays open,
            # so a sentence continues over the page break
            provs = _row_provs(rows, paragraphs[0], page_no=page_no)
            item = self.doc.add_text(label=label, text=paragraphs[0].text, prov=provs[0], parent=self._section,
                                     content_layer=_layer(label))
            item.prov.extend(provs[1:])
            return
        if self._open is not None and label == DocItemLabel.TEXT and continues(self._open[1], rows[paragraphs[0].spans[0].row], m, self.rtl):
            item, prev = self._open[0], self._open[1]
            first = paragraphs.pop(0)
            joined = join_paragraphs(prev, first, self.lexicon, self.stats)
            offset = len(joined) - len(first.text)
            item.text = item.orig = joined
            item.prov.extend(_row_provs(rows, first, offset, page_no))
            prev.text, prev.open_end = joined, first.open_end
            self.stats.continuations += 1
            self.stats.paragraphs -= 1
            if not paragraphs and first.open_end:
                self._open = (item, prev, m)
                return
        self._open = None
        for para in paragraphs:
            provs = _row_provs(rows, para, page_no=page_no)
            if single:
                item = self._add_text(label, para.text, provs[0])
            else:
                item = self.doc.add_text(label=label, text=para.text, prov=provs[0], parent=self._section,
                                         content_layer=_layer(label))
            item.prov.extend(provs[1:])
            if para.open_end and label == DocItemLabel.TEXT:
                self._open = (item, para, m)


def _row_provs(rows, para, offset: int = 0, page_no: int = 1):
    from docling_core.types.doc import ProvenanceItem

    by_index = {row.index: row for row in rows}
    return [ProvenanceItem(page_no=page_no, bbox=_box(by_index[s.row].bbox), charspan=(s.start + offset, s.end + offset))
            for s in para.spans if s.row in by_index]



def join_paragraphs(prev, nxt, lexicon=None, stats=None) -> str:
    """The separator (or mark removal) for continuing ``prev`` with ``nxt``; returns the joined text."""
    from legacy_recomposition import Stats

    stats = stats if stats is not None else Stats()
    if ends_with_mark(prev.text):
        removed, hyphenated = resolve_mark(prev.text, nxt.text, lexicon)
        if removed:
            stats.marks_removed += 1
            return prev.text[:-1] + nxt.text
        stats.marks_kept += 1
        stats.note("kept", prev.text, nxt.text)
        return prev.text + ("" if hyphenated else " ") + nxt.text
    stats.note("continued", prev.text, nxt.text)
    return prev.text + separator(prev.text, nxt.text) + nxt.text
