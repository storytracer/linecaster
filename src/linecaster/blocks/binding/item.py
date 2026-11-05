"""``BindItem``: an item's pages bound into one ``DoclingDocument`` (``linecaster.formats.docling``)."""
from __future__ import annotations

from datatrove.pipeline.base import PipelineStep

from ...data.page import Page
from ...formats.docling import DocumentBuilder, docling_dict, to_text
from ..base.page import page_of


class BindItem(PipelineStep):
    """One ``DoclingDocument`` per item from its pages (``linecaster.formats.docling.DocumentBuilder``):
    paragraphs continued across page breaks (``text="reflow"``), optional ``sections``, page ``n`` of the
    document = the item's ``n``-th page in order (``Page.sequence``, then page id).

    **A task must see whole items**: linecaster's run layout buckets page rows by item (one item in one
    file), and the pages of an item must arrive in one task. An item is emitted once all its pages have
    arrived (``page.metadata[count_key]``, as ``ItemTexts`` does) or when the input ends.

    Output: one ``Document`` per item, ``id`` = item id, ``text`` = the document's plain text (with
    furniture), metadata ``item_id``, ``page_ids``, ``pages``, ``text_mode``, ``sections``, ``docling``
    (the DoclingDocument as a dict) and ``region_of`` (item ref -> ``"<page_no>:<region id>"``, for the
    Markdown dividers). Write it with ``ItemDocumentWriter``."""

    type = "🔠 - LINECASTER"
    name = "📚 bind item"

    def __init__(self, transcription: str = "ocr", text: str = "reflow", sections: bool = False, rtl: bool = False,
                 count_key: str = "item_page_count"):
        super().__init__()
        from ...formats.docling import TEXT_MODES

        if text not in TEXT_MODES:
            raise ValueError(f"unknown text mode {text!r}; choose {', '.join(TEXT_MODES)}")
        self.transcription, self.text, self.sections, self.rtl, self.count_key = transcription, text, sections, rtl, count_key

    def _emit(self, item: str, pages: list[Page]):
        from datatrove.data import Document

        from ...data.transcription import Transcription
        from ...text.recomposition import Stats

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
