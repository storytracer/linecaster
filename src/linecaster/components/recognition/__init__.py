"""Recognition: the text of lines, regions and pages."""
from linecaster.components.recognition.line_recognizer import LineRecognizer
from linecaster.components.recognition.page_recognizer import PageRecognizer, RegionRecognizer

__all__ = ["LineRecognizer", "PageRecognizer", "RegionRecognizer"]
