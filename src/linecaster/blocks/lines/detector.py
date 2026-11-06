"""``LineDetector``: a line detection engine on every page (lines with their geometry), with its backend."""
from __future__ import annotations

from ..base.model import ModelBlock


class LineDetector(ModelBlock):
    """Detects the text lines of every page, with their geometry, by a line detection engine.

    Reads the page image; adds ``lines`` (polygons, boxes, baselines where the engine gives them: what its preset
    produces). Lines found on the whole page are assigned to the layout regions afterwards by a ``LineAssigner``.

    Example:
        LineDetector("pp-ocrv6-medium-det@1")
    """

    step = "lines"
    docs_args = {"backend": "pp-ocrv6-medium-det@1"}
