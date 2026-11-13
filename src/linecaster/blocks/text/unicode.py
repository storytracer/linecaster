"""``UnicodeNormalizer``: the as-written layer in Unicode NFC, right after recognition, as ``nfc`` edits (see
``linecaster.text.unicode`` for why it is a step of its own)."""
from __future__ import annotations

from ...data.page import Page
from ...errors import PipelineConfigError
from ...text.unicode import FORMS, normalize_transcription
from ..base.page import PageBlock


class UnicodeNormalizer(PageBlock):
    """Gives the as-written text of every line and word its Unicode NFC form, as an ``nfc`` edit where it differs.

    Right after recognition (``linecaster.text.unicode`` says why it is a step of its own): canonical equivalence
    only, never a compatibility form (NFKC folding belongs to the readable text variants). The readings stay as the
    recognizer gave them; ``Transcription.text_of`` and the page's text read the edits. Reads ``text``; adds
    ``nfc``. A page without the transcription passes unchanged; stat ``strings_changed`` counts the edits.

    Args:
        transcription: the transcription to normalize; also the datatrove document's ``text``.
        form: ``NFC``; any other form is refused (``PipelineConfigError``).
    """

    name = "unicode normalizer"
    parts_read = ("text",)
    parts_added = ("nfc",)

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
