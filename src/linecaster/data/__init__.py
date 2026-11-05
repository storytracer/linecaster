"""The data model: transcriptions (regions, lines, words), pages, items and texts, and the geometry helpers
(``linecaster.data.geometry``). Import-light: pydantic and numpy; no datatrove, saturate or engines."""
from .page import PAGE_KEY, Item, Page, PageImage, Text
from .transcription import BBox, Line, ModelInfo, Point, Region, Source, Transcription, Word

__all__ = [
    "PAGE_KEY", "BBox", "Item", "Line", "ModelInfo", "Page", "PageImage", "Point", "Region", "Source", "Text",
    "Transcription", "Word"
]
