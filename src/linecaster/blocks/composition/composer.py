"""``ComposePage``: page composition, the transcription's ``docling`` part from its regions, lines and tables
(``linecaster.formats.docling``).

In squiddleocr's order: ... recognition -> ``NormalizeUnicode`` -> tables -> ``Typography`` ->
``ComposePage`` -> writers; ``BindItem`` after them, on whole items. ``Typography`` changes regions and lines
(``linecaster.text.typography``); ``ComposePage`` fills the ``docling`` part from them.
"""
from __future__ import annotations

from ...data.page import Page
from ...formats.docling import REGION_MAP_KEY, DocumentBuilder, docling_dict
from ..base.page import PageStep


class ComposePage(PageStep):
    """Build the named transcription's ``docling`` part from its regions, lines and tables
    (``linecaster.formats.docling.DocumentBuilder``; one document per page, named after the page id).
    ``text``: ``lines`` (one row per line) or ``reflow`` (paragraphs; squiddleocr's default).
    ``sections``: every heading opens a Docling section group (JSON and DocLang gain the tree).

    The map from each Docling item to its layout region (``"<page_no>:<region id>"``) is kept in
    ``transcription.extra["docling_region_of"]``, for the Markdown dividers of the export writers."""

    name = "compose page"
    REGION_MAP = REGION_MAP_KEY

    def __init__(self, transcription: str = "ocr", text: str = "lines", rtl: bool = False, sections: bool = False):
        super().__init__()
        from ...formats.docling import TEXT_MODES

        if text not in TEXT_MODES:
            raise ValueError(f"unknown text mode {text!r}; choose {', '.join(TEXT_MODES)}")
        self.transcription, self.text, self.rtl, self.sections = transcription, text, rtl, sections

    def process_page(self, doc, page: Page) -> Page:
        t = page.transcriptions.get(self.transcription)
        if t is None:
            return page
        w = page.image.width if page.image else None
        h = page.image.height if page.image else None
        from ...text.recomposition import Stats

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






