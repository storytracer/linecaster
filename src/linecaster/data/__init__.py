"""The data model: pages, items and texts; annotation sets and transcriptions with their annotators, raw outputs
and annotations; content roles and rendering policies; references; the measurements vocabulary; the upgrade of
stored page records; and the geometry helpers (``linecaster.data.geometry``). Import-light: pydantic and numpy; no
datatrove, saturate or engines."""
from .measurements import FINISH_REASONS, MEASUREMENTS
from .page import PAGE_KEY, PAGE_SCHEMA, Item, Page, PageImage, Text
from .policy import DEFAULT_POLICY, LAYERS, ROLES, RenderingPolicy, RenderingRule
from .transcription import (
    DECISIONS, EDITS, LINKS, SCHEMES, STATUSES, Annotation, AnnotationSet, Annotator, Box, Cell, Classification,
    Decision, Description, DocumentRange, Edit, Formatting, Formula, Glyph, Line, Link, Paragraph, ParagraphRow, Point,
    Range, RawOutput, Reading, ReadingOrder, Ref, Region, Shape, Source, Table, Transcription, Word, Zone,
)

__all__ = [
    "DECISIONS", "DEFAULT_POLICY", "EDITS", "FINISH_REASONS", "LAYERS", "LINKS", "MEASUREMENTS", "PAGE_KEY",
    "PAGE_SCHEMA", "ROLES", "SCHEMES", "STATUSES", "Annotation", "AnnotationSet", "Annotator", "Box", "Cell",
    "Classification", "Decision", "Description", "DocumentRange", "Edit", "Formatting", "Formula", "Glyph", "Item",
    "Line", "Link", "Page", "PageImage", "Paragraph", "ParagraphRow", "Point", "Range", "RawOutput", "Reading",
    "ReadingOrder", "Ref", "Region", "RenderingPolicy", "RenderingRule", "Shape", "Source", "Table", "Text",
    "Transcription", "Word", "Zone",
]
