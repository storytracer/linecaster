"""``LineDetector``: a line detection engine on every page (lines with their geometry), with its backend."""
from __future__ import annotations

from ..base.model import ModelBlock


class LineDetector(ModelBlock):
    step = "lines"
