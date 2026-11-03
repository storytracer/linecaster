"""The transcription of one page: the contract every block reads and extends.

Coordinates are pixels of the page image the transcription was made on, origin top-left. Every
``bbox`` is ``[x, y, width, height]``; polygons and baselines are lists of ``[x, y]`` points. Values
keep the precision their producer gave them (a detector's float polygon stays float), so geometry
survives a JSON round trip exactly.

A page is transcribed in steps, each adding one part:

* a layout step fills ``regions`` (label, polygon, reading order);
* a line step fills ``lines`` with geometry only (``text`` is ``None``);
* a recognition step fills each line's ``text``, ``confidence`` and ``words``;
* an assembly step builds ``docling`` (the document structure) from regions and lines.

``regions`` is the layout contract between steps; ``docling`` is the document a reader exports.
Words are the finest level: a recogniser that has character cuts turns them into words itself.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

Point = list[float]
BBox = list[float]          # [x, y, width, height]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=False)


class Word(_Model):
    """A word of a recognised line."""

    id: str
    text: str
    bbox: BBox | None = None
    confidence: float | None = None
    hyphen: bool = False                     # the word ends in a line-end hyphen the typesetter added
    alternatives: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class Line(_Model):
    """A text line: geometry from a line step, text from a recognition step."""

    id: str
    region_id: str | None = None
    reading_order: int = 0                   # rank of the line on the page, 0-based
    row: int = 0                             # visual row within its region
    bbox: BBox
    polygon: list[Point] | None = None
    baseline: list[Point] | None = None
    score: float | None = None               # the line step's detection score
    text: str | None = None                  # None until a recognition step ran
    confidence: float | None = None
    alternatives: list[str] = Field(default_factory=list)
    words: list[Word] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class Region(_Model):
    """A layout region. ``label`` uses Docling's vocabulary (text, section_header, page_header, ...);
    ``raw_label`` is the producing model's own label."""

    id: str
    label: str
    raw_label: str = ""
    polygon: list[Point]
    bbox: BBox
    score: float | None = None
    reading_order: int | None = None         # None = the producer gave no order
    heading_level: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ModelInfo(_Model):
    """One model that contributed to the transcription, in the order the steps ran."""

    step: str                                # layout, lines, recognition, tables, formulas, page, ...
    name: str                                # e.g. kraken-ppocrv6-medium, PP-DocLayoutV3
    revision: str | None = None
    backend: str | None = None               # in-process or served (with the server's address)
    settings: dict[str, Any] = Field(default_factory=dict)
    measurements: dict[str, Any] = Field(default_factory=dict)   # seconds, tokens, device, ...


class Source(_Model):
    """Where the transcription comes from: produced here, or converted from a delivered file."""

    kind: str = "produced"                   # produced | converted | ground_truth
    format: str | None = None                # alto, page, hocr, text, ... for converted ones
    uri: str | None = None
    image_sha256: str | None = None          # the image the coordinates refer to
    image_width: int | None = None
    image_height: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class Transcription(_Model):
    """OCR, HTR or ground truth of one page."""

    regions: list[Region] = Field(default_factory=list)
    lines: list[Line] = Field(default_factory=list)
    docling: dict[str, Any] | None = None    # a DoclingDocument, serialised as docling-core dumps it
    language: str | None = None
    model: list[ModelInfo] = Field(default_factory=list)
    source: Source = Field(default_factory=Source)
    extra: dict[str, Any] = Field(default_factory=dict)

    # ---------------------------------------------------------------- derived
    def ordered_lines(self) -> list[Line]:
        return sorted(self.lines, key=lambda ln: ln.reading_order)

    @property
    def text(self) -> str:
        """The recognised lines in reading order, one per line (as written, as laid out, full page)."""
        return "\n".join(ln.text for ln in self.ordered_lines() if ln.text is not None)

    @property
    def confidence(self) -> float | None:
        """Mean line confidence, weighted by line length."""
        num = den = 0.0
        for ln in self.lines:
            if ln.confidence is not None and ln.text:
                num += ln.confidence * len(ln.text)
                den += len(ln.text)
        return num / den if den else None

    @property
    def objects(self) -> dict[str, list]:
        """Regions in the shape of a Hugging Face ``objects`` column: ``bbox`` and ``category`` lists."""
        regs = sorted(self.regions, key=lambda r: (r.reading_order is None, r.reading_order or 0))
        return {"bbox": [r.bbox for r in regs], "category": [r.label for r in regs]}

    def region(self, region_id: str) -> Region | None:
        return next((r for r in self.regions if r.id == region_id), None)

    def lines_of(self, region_id: str) -> list[Line]:
        return sorted((ln for ln in self.lines if ln.region_id == region_id), key=lambda ln: ln.reading_order)
