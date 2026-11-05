"""``NormalizeUnicode``: the as-written layer in one Unicode normalisation form (default NFC), right after
recognition (see ``linecaster.text.unicode`` for why it is a step of its own)."""
from __future__ import annotations

from ...data.page import Page
from ...text.unicode import FORMS, normalize_transcription
from ..base.page import PageStep


class NormalizeUnicode(PageStep):
    name = "unicode normalisation"

    def __init__(self, transcription: str = "ocr", form: str = "NFC"):
        if form not in FORMS:
            raise ValueError(f"form {form!r}; choose {', '.join(FORMS)}")
        self.name = f"unicode {form}"
        super().__init__()
        self.transcription, self.form = transcription, form
        self.primary = transcription

    def process_page(self, doc, page: Page) -> Page:
        t = page.transcriptions.get(self.transcription)
        if t is not None:
            n = normalize_transcription(t, self.form)
            if n:
                self.stat_update("strings_changed", value=n)
        return page
