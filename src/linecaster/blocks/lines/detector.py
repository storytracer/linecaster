"""``LinesStep``: a line detection engine on every page (lines with their geometry), with its backend."""
from __future__ import annotations

from ..base.model import ModelStep


class LinesStep(ModelStep):
    step = "lines"
