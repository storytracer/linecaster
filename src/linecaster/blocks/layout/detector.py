"""``LayoutDetector``: a layout engine on every page (regions with labels and reading order), with its backend.

``LayoutDetector("single-region@1")`` reads the whole page as one ``text`` region (the built-in engine
``layout.single-region.v1``, no model, in the pipeline's process only)."""
from __future__ import annotations

from ..base.model import ModelBlock


class LayoutDetector(ModelBlock):
    """Detects the layout regions of every page, with their labels and reading order, by a layout engine.

    Reads the page image; adds ``regions`` and ``reading_order`` (or what its preset produces) to the
    transcription: the regions with the model's own labels, each with a ``role`` classification from the DoclingDocument
    label its native label maps to (a layout preset's ``labels``), and a reading order, by the engine's annotator.
    ``LayoutDetector("single-region@1")`` reads the whole page as one ``text`` region (the built-in engine
    ``layout.single-region.v1``, no model, in the pipeline's process only).

    Example:
        LayoutDetector("pp-doclayoutv3@1")
        LayoutDetector("single-region@1")
    """

    step = "layout"
    docs_args = {"backend": "pp-doclayoutv3@1"}
