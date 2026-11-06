"""Recognition blocks with an engine and its backend: ``LineRecognizer`` (the text of every line),
``TableRecognizer`` (the structure of table regions) and ``FormulaRecognizer`` (LaTeX of formula regions)."""
from __future__ import annotations

from ..base.model import ModelBlock


class LineRecognizer(ModelBlock):
    """Recognizes the text of every line by a line recognition engine.

    Reads the page image and the transcription's ``lines``; adds ``text`` and what its preset produces (``words``,
    word and line confidences, ...), the lines in the order the line step left them. One page per call or request;
    an engine batches only the lines of one page.

    Example:
        from linecaster.backends import InProcess

        LineRecognizer("kraken-ppocrv6-medium@1")
        LineRecognizer(InProcess("linecaster_kraken:KrakenRecognitionEngine"))
    """

    step = "recognition"
    docs_args = {"backend": "kraken-ppocrv6-medium@1"}


class TableRecognizer(ModelBlock):
    """Recognizes the structure of every table region by a table engine.

    Reads the page image and the transcription's ``regions``; adds ``tables`` (the cells of each ``table`` region,
    or what its preset produces). A page without a ``table`` region gets no image: the engine has nothing to read.

    Example:
        TableRecognizer("slanet-plus@2")
    """

    step = "tables"
    region_label = "table"
    docs_args = {"backend": "slanet-plus@2"}


class FormulaRecognizer(ModelBlock):
    """Recognizes every formula region as LaTeX by a formula engine.

    Reads the page image and the transcription's ``regions``; adds ``formulas`` (or what its preset produces:
    ``latex``). A page without a ``formula`` region gets no image: the engine has nothing to read. A
    ``LineAssigner`` (or ``ModularTranscriber``) with ``formulas_separately`` leaves formula regions without lines
    for it.

    Example:
        FormulaRecognizer("pp-formulanet-plus-l@1")
    """

    step = "formulas"
    region_label = "formula"
    docs_args = {"backend": "pp-formulanet-plus-l@1"}
