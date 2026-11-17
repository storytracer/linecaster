"""``LineRecognizer``: the text of every line, by a line recognition engine."""
from __future__ import annotations

from linecaster.core.model import ModelComponent


class LineRecognizer(ModelComponent):
    """Recognizes the text of every line by a line recognition engine.

    Reads the page image and the transcription's ``lines``; adds ``text`` and what its preset produces (``words``,
    word and line confidences, ...): a reading of every line that has none, by the engine's annotator, the lines in
    the order the line step left them. One page per call or request;
    an engine batches only the lines of one page.

    Example:
        from linecaster.backends import InProcess

        LineRecognizer("kraken-ppocrv6-medium")
        LineRecognizer(InProcess("linecaster_kraken:KrakenRecognitionEngine"))
    """

    step = "recognition"
    docs_args = {"backend": "kraken-ppocrv6-medium"}
