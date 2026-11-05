"""``LayoutStep``: a layout engine on every page (regions with labels and reading order), with its backend."""
from __future__ import annotations

from ..base.model import ModelStep


class LayoutStep(ModelStep):
    step = "layout"
