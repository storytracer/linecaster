"""``ModularTranscriber``: the modular way to read a page's lines: layout -> lines -> line assignment -> line
recognition, each model step with its own engine and backend (``pipelines/transcribe_modular.py``)."""
from __future__ import annotations

from linecaster.core.composite import Composite
from linecaster.components.layout.layout_detector import LayoutDetector
from linecaster.components.lines.line_assigner import LineAssigner
from linecaster.components.lines.line_detector import LineDetector
from linecaster.components.recognition.line_recognizer import LineRecognizer


def _component(given, cls, transcription: str):
    """A component as given, or ``cls`` around a backend (``InProcess``, ``Served``, a preset's ref)."""
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
        layout: a ``LayoutDetector``, its backend, or a layout preset's ref; ``"single-region"`` reads the page as
            one region.
        formulas_separately: formula regions take no lines, for a formula step after it.
        direction: the writing direction the line assigner orders rows in (``horizontal-rl``: right to left;
            ``vertical-rl``, ``vertical-lr``: columns); ``None``: each region's recorded direction, else
            ``horizontal-lr`` (``LineAssigner``).
        transcription: the transcription every step works on (components given as components keep their own).
        name: the composite's name in the graph and the plan.

    Example:
        ModularTranscriber("pp-ocrv6-medium-det", "kraken-ppocrv6-medium", layout="pp-doclayoutv3")
    """

    docs_args = {"lines": "pp-ocrv6-medium-det", "recognition": "kraken-ppocrv6-medium",
                 "layout": "pp-doclayoutv3"}

    def __init__(self, lines, recognition, layout, formulas_separately: bool = False,
                 transcription: str = "ocr_new", name: str = "modular transcriber", direction: str | None = None):
        components = [
            _component(layout, LayoutDetector, transcription),
            _component(lines, LineDetector, transcription),
            LineAssigner(transcription=transcription, formulas_separately=formulas_separately, direction=direction),
            _component(recognition, LineRecognizer, transcription),
        ]
        super().__init__(name, components)
        self.transcription, self.formulas_separately = transcription, formulas_separately
