"""The transcription of one page: the contract every block reads and extends.

Coordinates are pixels of the page image the transcription was made on, origin top-left. Every
``bbox`` is ``[x, y, width, height]``; polygons and baselines are lists of ``[x, y]`` points. Values
keep the precision their producer gave them (a detector's float polygon stays float), so geometry
survives a JSON round trip exactly.

A page is transcribed in steps, each adding one part:

* a layout step fills ``regions`` (label, polygon, reading order);
* a line step fills ``lines`` with geometry only (``text`` is ``None``);
* a recognition step fills each line's ``text``, ``confidence`` and ``words``;
* recomposition (``Recomposer``) fills ``paragraphs`` (running text from the rows, with its decisions);
* character normalization (``CharacterNormalizer``) fills ``Line.normalized`` and ``Paragraph.normalized``;
* page composition (``Composer``) builds ``docling`` (the document structure) from regions and lines, or
  paragraphs.

Every step that worked on the transcription adds one ``StepInfo`` to ``steps``.

``regions`` is the layout contract between steps; ``docling`` is the document a reader exports.
Words are the finest level: a recognizer that has character cuts turns them into words itself.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Point = list[float]
BBox = list[float]          # [x, y, width, height]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=False)


class Word(_Model):
    """A word of a recognized line."""

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
    bbox: BBox | None = None                 # None for text-only transcriptions (a delivered plain text)
    polygon: list[Point] | None = None
    baseline: list[Point] | None = None
    score: float | None = None               # the line step's detection score
    text: str | None = None                  # None until a recognition step ran
    normalized: str | None = None            # the text normalized (CharacterNormalizer); None until that ran
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


class StepInfo(_Model):
    """One step that worked on the transcription, in the order the steps ran: a model step (layout, lines,
    recognition, tables, formulas) or a rule-based one (unicode, typography, recomposition, normalization,
    composition). ``measurements`` keys come from the fixed vocabulary ``linecaster.data.MEASUREMENTS``."""

    step: str                                # layout, lines, recognition, ..., unicode, typography, recomposition
    name: str                                # the model (kraken-ppocrv6-medium); without one, what ran (unicodedata)
    engine: str | None = None                # the engine's code id, e.g. kraken.recognition.v1 (None: no engine ran it)
    revision: str | None = None
    preset: str | None = None                # the catalog preset edition it ran as: id@edition
    preset_sha256: str | None = None         # the hash of that edition's functional content (catalog.lock)
    recipe: str | None = None                # the recipe edition the run followed: id@edition
    recipe_sha256: str | None = None
    backend: str | None = None               # in-process or served (with the server's address)
    settings: dict[str, Any] = Field(default_factory=dict)
    measurements: dict[str, Any] = Field(default_factory=dict)   # MEASUREMENTS: seconds, tokens, counts, ...


#: what a recomposition decided at a row end, and why: kind -> its reasons (``Decision``)
DECISIONS: dict[str, tuple[str, ...]] = {
    # a division mark the typesetter added, removed: the next row starts with a lowercase or caseless letter
    "mark_removed": ("letter_follows",),
    # a hyphen at a row end kept: the next row starts with a capital (a compound divided at its own hyphen), a
    # digit, or no letter; the next row is in another script (a Hebrew letter before the mark); or the document
    # attests the hyphenated form and not the joined one
    "hyphen_kept": ("capital_follows", "digit_follows", "no_letter_follows", "script_change", "attested"),
    # a new paragraph starts at this row: it is indented, a gap of about a blank line is above it, or (justified
    # text) the row before stopped short of the end margin
    "paragraph_break": ("indent", "gap", "short_row"),
    # the paragraph runs on into the next one (the next region, or the next page): it ends with a division
    # mark, or its last row reaches the end margin, without sentence-final punctuation
    "continuation": ("division_mark", "end_margin"),
}


class Decision(_Model):
    """One decision of a recomposition, at one row of a paragraph (``row``: the index into
    ``Paragraph.rows``): a mark removed or a hyphen kept at that row's end, a paragraph break before it (row
    0), a continuation after the paragraph's last row. ``kind`` and ``reason`` are ``DECISIONS``'.
    ``separator`` is, for a continuation, what joins this paragraph's text to the text of the paragraph it
    runs on into (``""`` or a space; a removed mark is already gone from ``Paragraph.text``)."""

    kind: Literal["mark_removed", "hyphen_kept", "paragraph_break", "continuation"]
    reason: str
    row: int = 0
    separator: str | None = None

    @model_validator(mode="after")
    def _reason(self):
        if self.reason not in DECISIONS[self.kind]:
            raise ValueError(f"{self.kind}: reason {self.reason!r} is none of {DECISIONS[self.kind]}")
        return self


class ParagraphRow(_Model):
    """One visual row of a paragraph: every line on the row (``Line.row``; empty ones too), and where the row's
    text is in the paragraph's text."""

    lines: list[str]                         # line ids, in the transcription's line order
    start: int                               # Paragraph.text[start:end] is this row's part
    end: int


class ParagraphRef(_Model):
    """A paragraph elsewhere: its id, on this page (``page_id`` None) or on another page of the item."""

    id: str
    page_id: str | None = None


class Paragraph(_Model):
    """Running text recomposed from the rows of one region, with the decisions that made it.

    The rows say exactly where each part of the text was printed, which is what a document's provenance needs:
    a ``ParagraphRow`` names the lines on the row (all of them, as ``Line.row`` groups a region's lines), and its
    box is the union of their boxes as algorithms derive them (``geometry.bbox_of`` of each polygon, else the
    bbox); ``start``/``end`` are the row's character range in ``text``, so a document item made from the paragraph
    has one provenance entry per row with that box and that ``charspan`` (shifted by the length of the text
    before it when the item continues a paragraph of an earlier region or page). Rows without text belong to no
    paragraph. A text-only transcription (lines without geometry) has rows too, without boxes.

    ``text`` is as written, flowed: the rows joined, the division marks the recomposition removed are gone
    (``decisions``). ``normalized`` is the same text normalized (``CharacterNormalizer``). ``continues`` names
    the paragraph this one runs on into, ``continues_from`` the one it continues (in the next or previous text
    region, or, from an item-level recomposition, on the next or previous page)."""

    id: str                                  # <region id>_p<n>
    region_id: str | None = None
    rows: list[ParagraphRow] = Field(default_factory=list)
    text: str = ""
    normalized: str | None = None
    continues_from: ParagraphRef | None = None
    continues: ParagraphRef | None = None
    decisions: list[Decision] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


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
    paragraphs: list[Paragraph] = Field(default_factory=list)   # in reading order (Recomposer)
    docling: dict[str, Any] | None = None    # a DoclingDocument, serialized as docling-core dumps it
    language: str | None = None
    steps: list[StepInfo] = Field(default_factory=list)          # one per step that worked on it, in order
    source: Source = Field(default_factory=Source)
    extra: dict[str, Any] = Field(default_factory=dict)

    # ---------------------------------------------------------------- derived
    def ordered_lines(self) -> list[Line]:
        return sorted(self.lines, key=lambda ln: ln.reading_order)

    @property
    def text(self) -> str:
        """The page's text as written, as laid out, full page: the recognized lines in reading order, one
        per line; a region with a table structure (``region.extra["table"]``, from a tables step) is
        written as a Markdown table instead of its lines (an HTML table when a cell spans)."""
        tables = {r.id: r.extra["table"] for r in self.regions if r.extra.get("table", {}).get("cells")}
        out, done = [], set()
        for ln in self.ordered_lines():
            if ln.region_id in tables:
                if ln.region_id not in done:
                    done.add(ln.region_id)
                    out.append(render_table(tables[ln.region_id]))
            elif ln.text is not None:
                out.append(ln.text)
        return "\n".join(out)

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

    # ---------------------------------------------------------------- transforms
    def scaled(self, sx: float, sy: float | None = None) -> "Transcription":
        """A copy with every coordinate scaled (region polygons and boxes, line boxes, polygons and
        baselines, word boxes): ``x * sx``, ``y * sy`` (``sy`` defaults to ``sx``). Use it to bring a
        transcription made on one image to a derivative of another size. ``source.image_width`` /
        ``image_height`` follow (rounded); the factors are recorded in ``source.extra["scale"]``
        (multiplied with an earlier one). ``docling`` provenance is not touched."""
        sy = sx if sy is None else sy
        t = self.model_copy(deep=True)

        def pts(p):
            return None if p is None else [[x * sx, y * sy] for x, y in p]

        def box(b):
            return None if b is None else [b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy]

        for r in t.regions:
            r.polygon, r.bbox = pts(r.polygon), box(r.bbox)
            for cell in (r.extra.get("table") or {}).get("cells", []):
                cell["bbox"] = box(cell.get("bbox"))
        for ln in t.lines:
            ln.bbox, ln.polygon, ln.baseline = box(ln.bbox), pts(ln.polygon), pts(ln.baseline)
            for w in ln.words:
                w.bbox = box(w.bbox)
        if t.source.image_width is not None:
            t.source.image_width = round(t.source.image_width * sx)
        if t.source.image_height is not None:
            t.source.image_height = round(t.source.image_height * sy)
        prev = t.source.extra.get("scale") or [1.0, 1.0]
        t.source.extra["scale"] = [prev[0] * sx, prev[1] * sy]
        return t

def render_table(table: dict) -> str:
    """A table structure (``cells`` with row, col, spans, text) as a Markdown pipe table, first row as the
    header; as an HTML table when any cell spans rows or columns (Markdown cannot hold spans)."""
    cells = table["cells"]
    if any(c.get("row_span", 1) > 1 or c.get("col_span", 1) > 1 for c in cells):
        rows: dict[int, list] = {}
        for c in sorted(cells, key=lambda c: (c["row"], c["col"])):
            span = "".join(f' {k}span="{c[k + "_span"]}"' for k in ("row", "col") if c.get(k + "_span", 1) > 1)
            tag = "th" if c.get("header") else "td"
            rows.setdefault(c["row"], []).append(f"<{tag}{span}>{_html_escape(c['text'])}</{tag}>")
        return "<table>" + "".join(f"<tr>{''.join(r)}</tr>" for _, r in sorted(rows.items())) + "</table>"
    n_rows = max((c["row"] + 1 for c in cells), default=0)
    n_cols = max((c["col"] + 1 for c in cells), default=0)
    grid = [[""] * n_cols for _ in range(n_rows)]
    for c in cells:
        grid[c["row"]][c["col"]] = " ".join(c["text"].split()).replace("|", "\\|")
    lines = ["| " + " | ".join(row) + " |" for row in grid]
    if lines:
        lines.insert(1, "|" + "|".join("---" for _ in range(n_cols)) + "|")
    return "\n".join(lines)


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
