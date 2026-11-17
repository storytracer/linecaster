"""``FormulaRecognizer``: every formula region as LaTeX, by a formula engine."""
from __future__ import annotations

from linecaster.core.model import ModelComponent


class FormulaRecognizer(ModelComponent):
    """Recognizes every formula region as LaTeX by a formula engine.

    Reads the page image and the transcription's ``regions``; adds ``formulas`` (a ``Formula`` annotation of each
    ``formula`` region, or what its preset produces: ``latex``). A page without a ``formula`` region gets no image: the engine has nothing to read. A
    ``LineAssigner`` (or ``ModularTranscriber``) with ``formulas_separately`` leaves formula regions without lines
    for it.

    Example:
        FormulaRecognizer("pp-formulanet-plus-l")
    """

    step = "formulas"
    region_label = "formula"
    docs_args = {"backend": "pp-formulanet-plus-l"}
