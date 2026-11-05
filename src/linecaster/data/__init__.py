"""The data model: transcriptions (regions, lines, words, paragraphs), pages, items and texts, the measurements
vocabulary, and the geometry helpers (``linecaster.data.geometry``). Import-light: pydantic and numpy; no
datatrove, saturate or engines."""
from .measurements import FINISH_REASONS, MEASUREMENTS
from .page import PAGE_KEY, PAGE_SCHEMA, Item, Page, PageImage, Text
from .transcription import (DECISIONS, BBox, Decision, Line, Paragraph, ParagraphRef, ParagraphRow, Point, Region,
                            Source, StepInfo, Transcription, Word)

__all__ = [
    "DECISIONS", "FINISH_REASONS", "MEASUREMENTS", "PAGE_KEY", "PAGE_SCHEMA", "BBox", "Decision", "Item", "Line",
    "Page", "PageImage", "Paragraph", "ParagraphRef", "ParagraphRow", "Point", "Region", "Source", "StepInfo", "Text",
    "Transcription", "Word"
]
