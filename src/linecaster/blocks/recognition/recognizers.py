"""Recognition blocks with an engine and its backend: ``LineRecognizer`` (the text of every line),
``TableRecognizer`` (the structure of table regions) and ``FormulaRecognizer`` (LaTeX of formula regions)."""
from __future__ import annotations

from ..base.model import ModelBlock


class LineRecognizer(ModelBlock):
    step = "recognition"


class TableRecognizer(ModelBlock):
    step = "tables"
    region_label = "table"


class FormulaRecognizer(ModelBlock):
    step = "formulas"
    region_label = "formula"
