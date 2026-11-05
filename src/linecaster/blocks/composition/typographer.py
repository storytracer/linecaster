"""``Typographer``: squiddleocr's retyper (``linecaster.text.typography``) on a page's transcription."""
from __future__ import annotations

from ...data.page import Page
from ...text.typography import retype
from ..base.page import PageBlock


class Typographer(PageBlock):
    """squiddleocr's retyper on the named transcription: heading levels from type size, headline
    splits, drop capitals, uncertain page numbers removed (see ``linecaster.text.typography``)."""

    name = "typographer"

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
