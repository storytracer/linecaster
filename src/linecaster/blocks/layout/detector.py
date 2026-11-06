"""``LayoutDetector``: a layout engine on every page (regions with labels and reading order), with its backend.

``LayoutDetector("single-region@1")`` reads the whole page as one ``text`` region (the built-in engine
``layout.single-region.v1``, no model, in the pipeline's process only)."""
from __future__ import annotations

from ..base.model import ModelBlock


class LayoutDetector(ModelBlock):
    step = "layout"
