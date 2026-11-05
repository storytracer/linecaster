"""``UnicodeNormalizer``: the as-written layer in one Unicode normalization form (default NFC), right after
recognition (see ``linecaster.text.unicode`` for why it is a step of its own)."""
from __future__ import annotations

from ...data.page import Page
from ...errors import PipelineConfigError
from ...text.unicode import FORMS, normalize_transcription
from ..base.page import PageBlock


class UnicodeNormalizer(PageBlock):
    name = "unicode normalizer"
    parts_read = ("text",)
    parts_added = ("nfc",)
    parts_replaced = ("text",)

    def __init__(self, transcription: str = "ocr_new", form: str = "NFC"):
        if form not in FORMS:
            raise PipelineConfigError(f"form {form!r}; choose {', '.join(FORMS)}")
        self.name = f"unicode normalizer ({form})"
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
