"""``BindItem``: an item's pages bound into one ``DoclingDocument``: the item-level recomposition and composition
(``recomposition.unicode.v1``, ``composition.docling.v1``) on whole items."""
from __future__ import annotations

from datatrove.pipeline.base import PipelineStep

from ...data.page import Page
from ...data.transcription import Transcription
from ...errors import PipelineConfigError
from ...formats.docling import docling_dict, to_text
from ..base.contract import Contract, Contracted, Part, parts
from ..base.item import gather

#: ``text``: the pages recomposed into paragraphs across their page breaks (``reflow``), or as laid out (``lines``)
TEXT_MODES = ("lines", "reflow")


class BindItem(Contracted, PipelineStep):
    """One ``DoclingDocument`` per item from its pages: with ``text="reflow"`` recomposed as one item
    (``recomposition.unicode.v1`` on all its pages in order: paragraphs continued across page breaks, the lexicon
    the item's), with ``text="lines"`` each text region as laid out; composed by ``composition.docling.v1``
    (optional ``sections``); page ``n`` of the document = the item's ``n``-th page in order (``Page.sequence``,
    then page id). Paragraphs the pages carry from a page-level recomposition are made anew for the item.

    **A task must see whole items**: linecaster's run layout buckets page records by item (one item in one
    file), and the pages of an item must arrive in one task. An item is emitted once all its pages have
    arrived (``page.metadata[count_key]``, as ``ItemTexts`` does) or when the input ends.

    Output: one ``Document`` per item, ``id`` = item id, ``text`` = the document's plain text (with
    furniture), metadata ``item_id``, ``page_ids``, ``pages``, ``text_mode``, ``sections``, ``docling``
    (the DoclingDocument as a dict) and ``region_of`` (item ref -> ``"<page_no>:<region id>"``, for the
    Markdown dividers). Write it with ``ItemDocumentWriter``."""

    type = "🔠 - LINECASTER"
    name = "📚 bind item"
    role = "binder"

    def contract(self) -> Contract:
        return Contract(unit="page", unit_out="item", role=self.role,
                        reads=parts(("regions", "lines"), self.transcription), adds=frozenset({Part("document")}))

    def __init__(self, transcription: str = "ocr_new", text: str = "reflow", sections: bool = False, rtl: bool = False,
                 count_key: str = "item_page_count"):
        super().__init__()
        if text not in TEXT_MODES:
            raise PipelineConfigError(f"unknown text mode {text!r}; choose {', '.join(TEXT_MODES)}")
        self.transcription, self.text, self.sections, self.rtl, self.count_key = transcription, text, sections, rtl, count_key

    def _emit(self, item: str, pages: list[Page]):
        from datatrove.data import Document

        from ...engines import DoclingCompositionEngine, UnicodeRecompositionEngine

        ids = [p.page_id for p in pages]
        ts = [(p.transcriptions.get(self.transcription) or Transcription()).model_copy(deep=True) for p in pages]
        with self.track_time():
            if self.text == "reflow":
                UnicodeRecompositionEngine(rtl=self.rtl)(ts, page_ids=ids)
            else:
                for t in ts:
                    t.paragraphs = []
            doc, region_of = DoclingCompositionEngine(sections=self.sections).item_document(
                ts, item, page_ids=ids, sizes=[(p.image.width, p.image.height) if p.image else (None, None)
                                               for p in pages])
        self.stat_update("items")
        if self.text == "reflow":
            for key in ("continuations", "marks_removed"):
                total = sum(t.steps[-2].measurements.get(key, 0) for t in ts)
                if total:
                    self.stat_update(key, value=total)
        yield Document(text=to_text(doc, furniture=True), id=item, metadata={
            "item_id": item, "page_ids": ids, "pages": len(pages), "text_mode": self.text,
            "sections": self.sections, "docling": docling_dict(doc), "region_of": region_of})

    def run(self, data, rank: int = 0, world_size: int = 1):
        for item, pages in gather(data, self, self.count_key):
            yield from self._emit(item, pages)
