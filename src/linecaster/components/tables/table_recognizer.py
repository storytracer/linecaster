"""``TableRecognizer``: the structure of every table region, by a table engine."""
from __future__ import annotations

from linecaster.core.model import ModelComponent


class TableRecognizer(ModelComponent):
    """Recognizes the structure of every table region by a table engine.

    Reads the page image and the transcription's ``regions``; adds ``tables`` (a ``Table`` annotation with the cells of
    each ``table`` region, or what its preset produces). A page without a ``table`` region gets no image: the engine has nothing to read.

    Example:
        TableRecognizer("slanet-plus")
    """

    step = "tables"
    region_label = "table"
    docs_args = {"backend": "slanet-plus"}
