"""Recognition: the text of lines, regions and pages, tables and formulas."""
from linecaster.blocks.recognition.chat import PageRecognizer, RegionRecognizer
from linecaster.blocks.recognition.recognizers import FormulaRecognizer, LineRecognizer, TableRecognizer

__all__ = ["PageRecognizer", "RegionRecognizer", "FormulaRecognizer", "LineRecognizer", "TableRecognizer"]
