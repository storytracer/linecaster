"""``ModularTranscriber``: the modular way to read a page's lines: layout -> lines -> line assignment -> line
recognition, each model step with its own engine and backend (``pipelines/transcribe_modular.py``)."""
from __future__ import annotations

from ..base.composite import Composite
from ..layout.detector import LayoutDetector
from ..lines.assigner import LineAssigner
from ..lines.detector import LineDetector
from ..recognition.recognizers import LineRecognizer


def _block(given, cls, transcription: str):
    """A block as given, or ``cls`` around a backend (``InProcess``, ``Served``, a preset's ref)."""
    return given if hasattr(given, "run") else cls(given, transcription=transcription)


class ModularTranscriber(Composite):
    """Regions (``layout``: a ``LayoutDetector``, its backend, or a layout preset; ``"single-region@1"`` reads the page
    as one region), lines on the whole page (``lines``: a ``LineDetector`` or its backend), the lines
    assigned to the regions and ordered (``LineAssigner``; with ``formulas_separately`` formula regions take no
    lines, for a formula step after it) and every line recognized (``recognition``: a ``LineRecognizer`` or its
    backend), in the transcription ``transcription``.

    Outward contract: reads the page image and record; adds regions, reading order, lines, their assignment to
    regions and the recognizer's parts (text, words, confidences: its preset's)."""

    def __init__(self, lines, recognition, layout, formulas_separately: bool = False,
                 transcription: str = "ocr_new", name: str = "modular transcriber"):
        blocks = [
            _block(layout, LayoutDetector, transcription),
            _block(lines, LineDetector, transcription),
            LineAssigner(transcription=transcription, formulas_separately=formulas_separately),
            _block(recognition, LineRecognizer, transcription),
        ]
        super().__init__(name, blocks)
        self.transcription, self.formulas_separately = transcription, formulas_separately
