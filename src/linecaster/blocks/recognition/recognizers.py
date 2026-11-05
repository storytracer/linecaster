"""Recognition blocks with an engine and its backend: ``RecognitionStep`` (the text of every line),
``TablesStep`` (the structure of table regions) and ``FormulasStep`` (LaTeX of formula regions)."""
from __future__ import annotations

from ..base.model import ModelStep


class RecognitionStep(ModelStep):
    step = "recognition"


class TablesStep(ModelStep):
    step = "tables"
    region_label = "table"


class FormulasStep(ModelStep):
    step = "formulas"
    region_label = "formula"
