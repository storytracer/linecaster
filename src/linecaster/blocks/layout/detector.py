"""``LayoutDetector``: a layout engine on every page (regions with labels and reading order), with its backend."""
from __future__ import annotations

from ..base.model import ModelBlock


class LayoutDetector(ModelBlock):
    step = "layout"
