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
    """Reads a page's lines the modular way: layout, lines on the whole page, line assignment, line recognition.

    Expands into a ``LayoutDetector``, a ``LineDetector``, a ``LineAssigner`` and a ``LineRecognizer``, each model
    step with its own engine and backend, in the transcription ``transcription``. Outward contract: reads the page
    image; adds regions, reading order, lines, their assignment to regions and the recognizer's parts (text,
    words, confidences: its preset's).

    Args:
        lines: a ``LineDetector``, its backend, or a lines preset's ref.
        recognition: a ``LineRecognizer``, its backend, or a recognition preset's ref.
        layout: a ``LayoutDetector``, its backend, or a layout preset's ref; ``"single-region@1"`` reads the page as
            one region.
        formulas_separately: formula regions take no lines, for a formula step after it.
        transcription: the transcription every step works on (blocks given as blocks keep their own).
        name: the composite's name in the graph and the plan.

    Example:
        ModularTranscriber("pp-ocrv6-medium-det@1", "kraken-ppocrv6-medium@1", layout="pp-doclayoutv3@1")
    """

    docs_args = {"lines": "pp-ocrv6-medium-det@1", "recognition": "kraken-ppocrv6-medium@1",
                 "layout": "pp-doclayoutv3@1"}

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
