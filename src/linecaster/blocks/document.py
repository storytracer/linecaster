"""Post-recognition blocks without a model: the retyper (``Typography``), document assembly per page
(``AssembleDocument``) and per item (``AssembleItemDocument``), and export files (``PageExportsWriter``,
``ItemExportsWriter``).

In squiddleocr's order: ... recognition -> ``NormalizeUnicode`` -> tables -> ``Typography`` ->
``AssembleDocument`` -> writers; ``AssembleItemDocument`` after them, on whole items.
``Typography`` changes regions and lines (``linecaster.retyper``); ``AssembleDocument`` fills the
transcription's ``docling`` part from them (``linecaster.document``); ``PageExportsWriter`` writes
``<page id><suffix>.md`` / ``.txt`` / ``.html`` / ``.doclang.xml`` / ``.json`` (the DoclingDocument) per
page.
"""
from __future__ import annotations

from datatrove.io import DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep

from ..document import EXPORT_FORMATS, REGION_MAP_KEY, DocumentBuilder, docling_dict, export, load_docling, to_text
from ..page import Page
from ..retyper import retype
from .base import PageStep, page_of


class Typography(PageStep):
    """squiddleocr's retyper on the named transcription: heading levels from type size, headline
    splits, drop capitals, uncertain page numbers removed (see ``linecaster.retyper``)."""

    name = "typography (retyper)"

    def __init__(self, transcription: str = "ocr"):
        super().__init__()
        self.transcription = transcription

    def process_page(self, doc, page: Page) -> Page:
        t = page.transcriptions.get(self.transcription)
        if t is None:
            return page
        stats = retype(t)
        for key in ("levelled", "demoted", "split", "drop_capitals", "numbers_dropped"):
            if getattr(stats, key):
                self.stat_update(key, value=getattr(stats, key))
        return page


class AssembleDocument(PageStep):
    """Build the named transcription's ``docling`` part from its regions, lines and tables
    (``linecaster.document.DocumentBuilder``; one document per page, named after the page id).
    ``text``: ``lines`` (one row per line) or ``reflow`` (paragraphs; squiddleocr's default).
    ``sections``: every heading opens a Docling section group (JSON and DocLang gain the tree).

    The map from each Docling item to its layout region (``"<page_no>:<region id>"``) is kept in
    ``transcription.extra["docling_region_of"]``, for the Markdown dividers of the export writers."""

    name = "assemble document"
    REGION_MAP = REGION_MAP_KEY

    def __init__(self, transcription: str = "ocr", text: str = "lines", rtl: bool = False, sections: bool = False):
        super().__init__()
        from ..document import TEXT_MODES

        if text not in TEXT_MODES:
            raise ValueError(f"unknown text mode {text!r}; choose {', '.join(TEXT_MODES)}")
        self.transcription, self.text, self.rtl, self.sections = transcription, text, rtl, sections

    def process_page(self, doc, page: Page) -> Page:
        t = page.transcriptions.get(self.transcription)
        if t is None:
            return page
        w = page.image.width if page.image else None
        h = page.image.height if page.image else None
        from ..reflow import Stats

        stats = Stats()
        b = DocumentBuilder(page.page_id, text=self.text, sections=self.sections, rtl=self.rtl, stats=stats)
        b.add_page(t, w, h)
        t.docling = docling_dict(b.build())
        t.extra[self.REGION_MAP] = dict(b.region_of)
        self.stat_update("documents")
        if self.text == "reflow":
            for key in ("paragraphs", "continuations", "marks_removed", "marks_kept"):
                if getattr(stats, key):
                    self.stat_update(key, value=getattr(stats, key))
        return page


class PageExportsWriter(PipelineStep):
    """Write each page's document exports as files named ``<page id><suffix>.<ext>`` in
    ``output_folder``: ``md`` (Markdown), ``txt`` (text), ``html``, ``doclang`` (DocLang XML) and
    ``json`` (the DoclingDocument), all docling-core's serialisers (``linecaster.document.export``).
    ``furniture`` keeps page headers and footers in md, txt and html (squiddleocr's ``--furniture``);
    ``dividers`` puts ``---`` between the items of consecutive layout regions in md (needs the region
    map ``AssembleDocument`` keeps). Pages pass through."""

    type = "💽 - WRITER"
    name = "📝 page exports"

    EXTENSIONS = EXPORT_FORMATS

    def __init__(self, output_folder: DataFolderLike, formats: tuple[str, ...] = ("md", "txt"), suffix: str = "",
                 furniture: bool = False, transcription: str = "ocr", dividers: bool = False):
        super().__init__()
        unknown = set(formats) - set(self.EXTENSIONS)
        if unknown:
            raise ValueError(f"unknown formats {sorted(unknown)}; choose from {sorted(self.EXTENSIONS)}")
        self.folder, self.formats, self.suffix = get_datafolder(output_folder), tuple(formats), suffix
        self.furniture, self.transcription, self.dividers = furniture, transcription, dividers

    def run(self, data, rank: int = 0, world_size: int = 1):
        for doc in data:
            page = page_of(doc)
            t = page.transcriptions.get(self.transcription)
            if t is None or t.docling is None:
                self.stat_update("no_document")
                yield doc
                continue
            with self.track_time():
                d = load_docling(t)
                region_of = t.extra.get(AssembleDocument.REGION_MAP) if self.dividers else None
                for fmt in self.formats:
                    content = t.docling if fmt == "json" else d
                    with self.folder.open(f"{page.page_id}{self.suffix}.{self.EXTENSIONS[fmt]}", "wt", encoding="utf-8") as f:
                        f.write(export(content, fmt, self.furniture, region_of))
                    self.stat_update(fmt)
            yield doc


class AssembleItemDocument(PipelineStep):
    """One ``DoclingDocument`` per item from its pages (``linecaster.document.DocumentBuilder``):
    paragraphs continued across page breaks (``text="reflow"``), optional ``sections``, page ``n`` of the
    document = the item's ``n``-th page in order (``Page.sequence``, then page id).

    **A task must see whole items**: linecaster's run layout buckets page rows by item (one item in one
    file), and the pages of an item must arrive in one task. An item is emitted once all its pages have
    arrived (``page.metadata[count_key]``, as ``ItemTexts`` does) or when the input ends.

    Output: one ``Document`` per item, ``id`` = item id, ``text`` = the document's plain text (with
    furniture), metadata ``item_id``, ``page_ids``, ``pages``, ``text_mode``, ``sections``, ``docling``
    (the DoclingDocument as a dict) and ``region_of`` (item ref -> ``"<page_no>:<region id>"``, for the
    Markdown dividers). Write it with ``ItemExportsWriter``."""

    type = "🔠 - LINECASTER"
    name = "📚 assemble item document"

    def __init__(self, transcription: str = "ocr", text: str = "reflow", sections: bool = False, rtl: bool = False,
                 count_key: str = "item_page_count"):
        super().__init__()
        from ..document import TEXT_MODES

        if text not in TEXT_MODES:
            raise ValueError(f"unknown text mode {text!r}; choose {', '.join(TEXT_MODES)}")
        self.transcription, self.text, self.sections, self.rtl, self.count_key = transcription, text, sections, rtl, count_key

    def _emit(self, item: str, pages: list[Page]):
        from datatrove.data import Document

        from ..reflow import Stats
        from ..transcription.model import Transcription

        pages = sorted(pages, key=lambda p: (p.sequence is None, p.sequence or 0, p.page_id))
        stats = Stats()
        with self.track_time():
            b = DocumentBuilder(item, text=self.text, sections=self.sections, rtl=self.rtl, stats=stats)
            for p in pages:
                t = p.transcriptions.get(self.transcription) or Transcription()
                b.add_page(t, p.image.width if p.image else None, p.image.height if p.image else None)
            doc = b.build()
        self.stat_update("items")
        for key in ("continuations", "marks_removed"):
            if getattr(stats, key):
                self.stat_update(key, value=getattr(stats, key))
        yield Document(text=to_text(doc, furniture=True), id=item, metadata={
            "item_id": item, "page_ids": [p.page_id for p in pages], "pages": len(pages), "text_mode": self.text,
            "sections": self.sections, "docling": docling_dict(doc), "region_of": dict(b.region_of)})

    def run(self, data, rank: int = 0, world_size: int = 1):
        items: dict[str, list[Page]] = {}
        for doc in data:
            page = page_of(doc)
            self.stat_update("pages")
            item = page.item_id or doc.id
            items.setdefault(item, []).append(page)
            expected = page.metadata.get(self.count_key)
            if expected and len(items[item]) >= expected:
                yield from self._emit(item, items.pop(item))
        for item, pages in items.items():
            if any(p.metadata.get(self.count_key) for p in pages):
                self.stat_update("incomplete_items")
            yield from self._emit(item, pages)


class ItemExportsWriter(PipelineStep):
    """Write ``AssembleItemDocument``'s documents as ``<item id><suffix>.<ext>``: ``md``, ``txt``,
    ``html``, ``doclang``, ``json`` (``linecaster.document.export``). ``furniture`` keeps page headers
    and footers in md, txt and html; ``dividers`` puts ``---`` between the items of consecutive layout
    regions in md. Documents pass through."""

    type = "💽 - WRITER"
    name = "📝 item exports"

    def __init__(self, output_folder: DataFolderLike, formats: tuple[str, ...] = ("md", "txt"), suffix: str = "",
                 furniture: bool = False, dividers: bool = False):
        super().__init__()
        unknown = set(formats) - set(EXPORT_FORMATS)
        if unknown:
            raise ValueError(f"unknown formats {sorted(unknown)}; choose from {', '.join(EXPORT_FORMATS)}")
        self.folder, self.formats, self.suffix = get_datafolder(output_folder), tuple(formats), suffix
        self.furniture, self.dividers = furniture, dividers

    def run(self, data, rank: int = 0, world_size: int = 1):
        from docling_core.types.doc import DoclingDocument

        for doc in data:
            meta = doc.metadata
            if "docling" not in meta:
                self.stat_update("no_document")
                yield doc
                continue
            with self.track_time():
                d = DoclingDocument.model_validate(meta["docling"])
                region_of = meta.get("region_of") if self.dividers else None
                for fmt in self.formats:
                    content = meta["docling"] if fmt == "json" else d
                    with self.folder.open(f"{meta['item_id']}{self.suffix}.{EXPORT_FORMATS[fmt]}", "wt",
                                          encoding="utf-8") as f:
                        f.write(export(content, fmt, self.furniture, region_of))
                    self.stat_update(fmt)
            yield doc
