"""What is read from a page: annotation sets, their annotators and raw outputs, and their annotations.

An **annotation set** (``AnnotationSet``) is everything one source said about one page; a **transcription**
(``Transcription``) is one that also holds text. Every step adds to a set and changes nothing in it: an annotator
(``Annotator``) is appended, then the annotations it made, each naming the annotator by its index in
``annotators`` (and the raw output it was parsed from by its index in ``outputs``). A normalization, a correction, a
relabelling, a removal are new annotations (``Edit``, ``Classification``) about an earlier one.

Coordinates are pixels of the page image, origin top-left: every ``box`` is ``[x, y, width, height]``; polygons and
baselines are lists of ``[x, y]`` points, exactly as their annotator gave them.

What a region *is* (its content role, its heading level) and how the page is read (``ReadingOrder``) are
annotations too; the accessors below resolve them (the latest annotator's counts unless a rendering policy says
otherwise). Which annotations go into which text is the rendering policy's (``linecaster.data.policy``).
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, model_validator

Point = list[float]
Box = list[float]               # [x, y, width, height]
Ref = str                       # a reference (linecaster.data.refs)

#: the format of a stored page record
SCHEMA = "linecaster.page/3"

_EXTENSION = re.compile(r"^[a-z][a-z0-9_]*__[a-z0-9_]+$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=False, populate_by_name=True)


def _check_namespaced(model):
    for key in model.__pydantic_extra__ or {}:
        if not _EXTENSION.match(key):
            raise ValueError(f"{type(model).__name__}: field {key!r} is neither a field nor namespaced (ns__field)")
    return model


class _Extensible(_Model):
    """A class that takes namespaced extension fields, ``<ns>__<field>`` (``lighton__continuation``)."""

    model_config = ConfigDict(extra="allow", validate_assignment=False, populate_by_name=True)

    @model_validator(mode="after")
    def _namespaced(self):
        return _check_namespaced(self)

    @property
    def extensions(self) -> dict[str, Any]:
        """The extension fields, by name."""
        return dict(self.__pydantic_extra__ or {})


# ---------------------------------------------------------------------------------------------- provenance
#: the steps whose annotators are rules (no model), for annotators upgraded from page/2 and for ``Annotator.kind``
RULE_STEPS = frozenset({"unicode", "typography", "recomposition", "normalization", "composition", "assignment",
                        "ordering", "image"})


class Annotator(_Model):
    """One thing that worked on an annotation set: a model step, a rule-based step, a delivered file, or people.
    ``measurements`` keys come from the fixed vocabulary ``linecaster.data.MEASUREMENTS``."""

    kind: Literal["model", "rule", "file", "human"] = "model"
    step: str                                # layout, lines, recognition, ..., unicode, typography; transcription
    name: str                                # the model; without one, what ran; for people, the group
    engine: str | None = None                # the engine's code id, e.g. kraken.recognition.v1
    revision: str | None = None
    preset: str | None = None                # the catalog preset edition it ran as: id@edition
    preset_sha256: str | None = None
    recipe: str | None = None                # the recipe edition the run followed: id@edition
    recipe_sha256: str | None = None
    backend: str | None = None               # in-process or served (with the server's address)
    run: str | None = None                   # the run id (RunRecord.run_id)
    settings: dict[str, Any] = Field(default_factory=dict)
    measurements: dict[str, Any] = Field(default_factory=dict)


class RawOutput(_Model):
    """One request's answer, verbatim: a completion as the model wrote it, or an engine's native result."""

    annotator: int
    content: str | dict | list
    format: str = "text"                     # text | json | <engine>
    pass_: int = Field(1, alias="pass")      # the page's request it is: 1, 2 after a repair pass
    kept: bool = True                        # the annotations were parsed from it
    settings: dict[str, Any] = Field(default_factory=dict)   # where this request differs from the annotator's
    image_size: list[int] | None = None      # the image sent, when it is not the page image
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None


class Source(_Extensible):
    """Where an annotation set comes from: produced here, converted from a delivered file, or a ground truth."""

    kind: Literal["produced", "converted", "ground_truth"] = "produced"
    format: str | None = None                # alto, page, hocr, docling, text, markdown, ...
    uri: str | None = None
    sha256: str | None = None                # of the delivered file
    dataset: str | None = None               # repo@revision
    record: str | None = None                # the row or file the set was read from
    image_sha256: str | None = None          # the image the coordinates refer to
    image_width: int | None = None
    image_height: int | None = None
    scale: list[float] | None = None         # [sx, sy] the set was scaled by (AnnotationSet.scaled)


# ---------------------------------------------------------------------------------------------- annotations
class Annotation(_Extensible):
    """What every annotation has: its annotator, the raw output it was parsed from, what it was derived from, and
    the annotator's confidence."""

    annotator: int
    output: int | None = None
    derived_from: list[Ref] = Field(default_factory=list)
    confidence: float | None = None


class Shape(_Model):
    """Geometry on the page image, without an annotator of its own."""

    box: Box | None = None
    polygon: list[Point] | None = None


class Formatting(_Model):
    """docling-core's ``Formatting``; on a reading, over ``charspan`` of its text."""

    charspan: list[int] | None = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    script: Literal["baseline", "sub", "super"] = "baseline"


class Glyph(Shape):
    text: str
    confidence: float | None = None


class Word(Shape):
    """A word of a reading. ``id`` only when its source gave one other than ``<line>_w<n>``."""

    model_config = ConfigDict(extra="allow", validate_assignment=False, populate_by_name=True)

    text: str
    id: str | None = None
    confidence: float | None = None
    hyphen: bool = False                     # ends in a division mark the typesetter added
    alternatives: list[str] = Field(default_factory=list)
    formatting: Formatting | None = None
    glyphs: list[Glyph] = Field(default_factory=list)

    @model_validator(mode="after")
    def _namespaced(self):
        return _check_namespaced(self)

    @property
    def extensions(self) -> dict[str, Any]:
        return dict(self.__pydantic_extra__ or {})


class Reading(Annotation):
    """What a recognizer read on one line: exactly as the engine produced it."""

    text: str
    alternatives: list[str] = Field(default_factory=list)
    words: list[Word] = Field(default_factory=list)
    formatting: list[Formatting] = Field(default_factory=list)


class Zone(Annotation):
    """A place on the page image an annotator found. ``id`` never contains ``#``, ``/`` or ``[``."""

    id: str
    box: Box | None = None
    polygon: list[Point] | None = None
    parent: str | None = None                # the zone it lies in


class Region(Zone):
    """A zone from a layout step; ``label`` is the annotator's own, verbatim."""

    label: str = ""


class Line(Zone):
    """A line zone, with the region it was assigned to and, once recognized, its reading."""

    region: str | None = None
    baseline: list[Point] | None = None
    reading: Reading | None = None

    def word_id(self, n: int) -> str:
        w = self.reading.words[n]
        return w.id or f"{self.id}_w{n}"


class Cell(Shape):
    """docling-core's ``TableCell``, lean: offsets (end exclusive), no spans, no grid."""

    start_row: int
    end_row: int
    start_col: int
    end_col: int
    text: str = ""
    column_header: bool = False
    row_header: bool = False
    row_section: bool = False

    @property
    def row_span(self) -> int:
        return self.end_row - self.start_row

    @property
    def col_span(self) -> int:
        return self.end_col - self.start_col

    @property
    def ref(self) -> str:
        return f"r{self.start_row}c{self.start_col}"


class Table(Annotation):
    """A region's table structure; ``html`` as the model wrote it, when it did."""

    target: Ref
    num_rows: int
    num_cols: int
    cells: list[Cell] = Field(default_factory=list)
    html: str | None = None


class Formula(Annotation):
    target: Ref
    latex: str


#: classification schemes
SCHEMES = ("role", "production", "heading_level", "language", "script", "status", "picture_class", "code_language")
STATUSES = ("illegible", "gap", "suppressed", "duplicate", "removed")


class Classification(Annotation):
    """One value of one scheme for one target."""

    target: Ref
    scheme: str
    value: str


class Description(Annotation):
    """Text an annotator wrote about a zone that is not on the page (docling-core's ``DescriptionMetaField``)."""

    target: Ref
    kind: str = "description"                # description | data | note
    text: str
    format: str = "text"                     # text | markdown | html


#: edit kinds, in the order a text's forms are made
EDITS = ("nfc", "joined", "corrected", "normalized", "expanded", "regularized")


class Edit(Annotation):
    """Another form of a target's text; the target's own text stays."""

    target: Ref
    kind: Literal["nfc", "normalized", "corrected", "joined", "expanded", "regularized"]
    text: str


#: link kinds: ``source`` is ``target``'s caption, note; continues it (a paragraph or footnote from an earlier
#: column or page); runs on into it; refers to it
LINKS = ("caption_of", "note_of", "continues", "runs_into", "refers_to")


class Link(Annotation):
    kind: str
    source: Ref
    target: Ref


class ReadingOrder(Annotation):
    """An order of the page: its regions in reading order, its lines in reading order, and each of those lines'
    visual row within its region (``rows``, parallel to ``lines``). An order of regions only leaves ``lines`` empty."""

    regions: list[str] = Field(default_factory=list)
    lines: list[str] = Field(default_factory=list)
    rows: list[int] = Field(default_factory=list)


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
    """One decision of a recomposition, at one row of a paragraph (``row``: the index into ``Paragraph.rows``).
    ``separator`` is, for a continuation, what joins this piece's text to the next piece's."""

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
    """One visual row of a paragraph: every line on the row, and the row's part of the paragraph's text."""

    lines: list[str]
    charspan: list[int]                      # [start, end] in Paragraph.text


class Range(Annotation):
    """A logical unit of content: its piece on this page. Pieces with the same id on other pages of the item are
    the same range."""

    id: str
    kind: str
    parent: str | None = None
    parts: list[Ref] = Field(default_factory=list)
    title: str | None = None


class DocumentRange(Range):
    """A document within or across items; ``kind`` is always written (``kind="document"``)."""

    kind: Literal["document"]


class Paragraph(Range):
    """The bottom range: running text recomposed from rows of lines, with the decisions that made it."""

    kind: Literal["paragraph"] = "paragraph"
    text: str = ""
    rows: list[ParagraphRow] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)

    @property
    def region(self) -> str | None:
        return self.parts[0] if self.parts else None


def _range_kind(v: Any) -> str:
    kind = v.get("kind", "paragraph") if isinstance(v, dict) else getattr(v, "kind", "paragraph")
    return kind if kind in ("paragraph", "document") else "range"


AnyRange = Annotated[Annotated[Paragraph, Tag("paragraph")] | Annotated[DocumentRange, Tag("document")]
                     | Annotated[Range, Tag("range")], Discriminator(_range_kind)]


# ---------------------------------------------------------------------------------------------- sets
class AnnotationSet(_Extensible):
    """Everything one source said about one page."""

    source: Source = Field(default_factory=Source)
    annotators: list[Annotator] = Field(default_factory=list)
    outputs: list[RawOutput] = Field(default_factory=list)
    regions: list[Region] = Field(default_factory=list)
    ranges: list[AnyRange] = Field(default_factory=list)
    classifications: list[Classification] = Field(default_factory=list)
    descriptions: list[Description] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    orders: list[ReadingOrder] = Field(default_factory=list)

    # ------------------------------------------------------------------ adding
    def add_annotator(self, annotator: Annotator) -> int:
        """Appends ``annotator`` and returns its index, which its annotations name."""
        self.annotators.append(annotator)
        return len(self.annotators) - 1

    def add_output(self, output: RawOutput) -> int:
        self.outputs.append(output)
        return len(self.outputs) - 1

    def add_region(self, annotator: int, id: str, box: Box | None = None, polygon: list[Point] | None = None,
                   label: str = "", role: str | None = None, heading_level: int | None = None, **fields) -> Region:
        """Appends a region and, with ``role`` (a content role or a Docling label), its ``role`` classification
        (and a ``heading_level`` one), all by ``annotator``."""
        from .policy import classify_label
        r = Region(annotator=annotator, id=id, box=box, polygon=polygon, label=label, **fields)
        self.regions.append(r)
        if role is not None:
            classify_label(self, annotator, id, role)
        if heading_level is not None:
            self.classify(annotator, id, "heading_level", heading_level)
        return r

    def add_order(self, annotator: int, regions: Iterable[str] = (), lines: Iterable[str] = (),
                  rows: Iterable[int] | None = None) -> ReadingOrder:
        """Appends a reading order: region ids, line ids (and their rows, 0 for each by default) in order."""
        lines = list(lines)
        o = ReadingOrder(annotator=annotator, regions=list(regions), lines=lines,
                         rows=list(rows) if rows is not None else [0] * len(lines))
        self.orders.append(o)
        return o

    def classify(self, annotator: int, target: Ref, scheme: str, value: Any, **fields) -> Classification:
        c = Classification(annotator=annotator, target=target, scheme=scheme, value=str(value), **fields)
        self.classifications.append(c)
        return c

    # ------------------------------------------------------------------ resolving
    def region(self, region_id: str) -> Region | None:
        return next((r for r in self.regions if r.id == region_id), None)

    def classifications_of(self, target: Ref, scheme: str) -> list[Classification]:
        return [c for c in self.classifications if c.target == target and c.scheme == scheme]

    def classification(self, target: Ref, scheme: str, precedence: Iterable[str] | None = None) -> str | None:
        """The value of ``scheme`` for ``target``: by the first step or annotator name in ``precedence`` that gave
        one, else by the latest annotator that did."""
        found = self.classifications_of(target, scheme)
        if not found:
            return None
        if precedence:
            for who in precedence:
                for c in reversed(found):
                    a = self.annotators[c.annotator] if c.annotator < len(self.annotators) else None
                    if a is not None and who in (a.step, a.name):
                        return c.value
        return max(enumerate(found), key=lambda ic: (ic[1].annotator, ic[0]))[1].value

    def role(self, target: Ref, precedence: Iterable[str] | None = None) -> str | None:
        """The content role of ``target`` (``linecaster.data.policy.ROLES``)."""
        return self.classification(target, "role", precedence)

    def label(self, target: Ref) -> str:
        """The Docling label of a region, from its content role (``linecaster.data.policy.docling_label``)."""
        from .policy import docling_label
        return docling_label(self, target)

    def heading_level(self, target: Ref) -> int | None:
        v = self.classification(target, "heading_level")
        return int(v) if v is not None else None

    def status(self, target: Ref) -> str | None:
        return self.classification(target, "status")

    def descriptions_of(self, target: Ref) -> list[Description]:
        return [d for d in self.descriptions if d.target == target]

    def order(self, of: str = "regions", precedence: Iterable[str] | None = None) -> ReadingOrder | None:
        """The reading order that counts for ``of`` (``regions`` or ``lines``): of the orders that give one, the
        first by ``precedence`` (steps or annotator names), else the latest."""
        found = [o for o in self.orders if getattr(o, of)]
        if not found:
            return None
        for who in precedence or ():
            for o in reversed(found):
                a = self.annotators[o.annotator] if o.annotator < len(self.annotators) else None
                if a is not None and who in (a.step, a.name):
                    return o
        return found[-1]

    def region_ranks(self) -> dict[str, int]:
        """Region id -> its rank in the reading order (regions it leaves out: none)."""
        o = self.order("regions")
        return {rid: i for i, rid in enumerate(o.regions)} if o is not None else {}

    def ordered_regions(self) -> list[Region]:
        """The regions in reading order; those the order leaves out last, in list order."""
        ranks = self.region_ranks()
        return sorted(self.regions, key=lambda r: ranks.get(r.id, len(ranks)))

    @property
    def paragraphs(self) -> list[Paragraph]:
        return [r for r in self.ranges if isinstance(r, Paragraph)]

    def link(self, source: Ref, kind: str) -> Ref | None:
        """The target of the latest link of ``kind`` from ``source``."""
        return next((ln.target for ln in reversed(self.links) if ln.source == source and ln.kind == kind), None)

    def range(self, range_id: str) -> Range | None:
        return next((r for r in self.ranges if r.id == range_id), None)

    @property
    def objects(self) -> dict[str, list]:
        """Regions in the shape of a Hugging Face ``objects`` column: ``bbox`` and ``category`` (the Docling label)
        lists, in reading order."""
        regs = [r for r in self.ordered_regions() if r.box is not None]
        return {"bbox": [r.box for r in regs], "category": [self.label(r.id) for r in regs]}

    # ------------------------------------------------------------------ transforms
    def scaled(self, sx: float, sy: float | None = None):
        """A copy with every coordinate scaled: ``x * sx``, ``y * sy`` (``sy`` defaults to ``sx``); the image size
        follows (rounded), and the factors are recorded in ``source.scale`` (multiplied with an earlier one)."""
        sy = sx if sy is None else sy
        t = self.model_copy(deep=True)

        def pts(p):
            return None if p is None else [[x * sx, y * sy] for x, y in p]

        def box(b):
            return None if b is None else [b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy]

        for z in [*t.regions, *getattr(t, "lines", [])]:
            z.box, z.polygon = box(z.box), pts(z.polygon)
            if isinstance(z, Line):
                z.baseline = pts(z.baseline)
                if z.reading is not None:
                    for w in z.reading.words:
                        w.box = box(w.box)
                        for g in w.glyphs:
                            g.box = box(g.box)
        for tb in getattr(t, "tables", []):
            for cell in tb.cells:
                cell.box = box(cell.box)
        if t.source.image_width is not None:
            t.source.image_width = round(t.source.image_width * sx)
        if t.source.image_height is not None:
            t.source.image_height = round(t.source.image_height * sy)
        prev = t.source.scale or [1.0, 1.0]
        t.source.scale = [prev[0] * sx, prev[1] * sy]
        return t


class Transcription(AnnotationSet):
    """An annotation set that also holds text: OCR, HTR or ground truth of one page."""

    lines: list[Line] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    formulas: list[Formula] = Field(default_factory=list)
    edits: list[Edit] = Field(default_factory=list)

    # ------------------------------------------------------------------ adding
    def add_line(self, annotator: int, id: str, box: Box | None = None, polygon: list[Point] | None = None,
                 region: str | None = None, baseline: list[Point] | None = None, text: str | None = None,
                 reader: int | None = None, **fields) -> Line:
        """Appends a line zone; with ``text``, also its reading, by ``reader`` (``annotator`` by default)."""
        ln = Line(annotator=annotator, id=id, box=box, polygon=polygon, region=region, baseline=baseline, **fields)
        self.lines.append(ln)
        if text is not None:
            self.read(reader if reader is not None else annotator, ln, text)
        return ln

    def read(self, annotator: int, line: Line | str, text: str, confidence: float | None = None,
             words: Iterable[Word] = (), alternatives: Iterable[str] = (), output: int | None = None,
             **fields) -> Reading:
        """Gives a line its reading; a line that has one already is a ``ValueError`` (one reading per line and set)."""
        ln = self.line(line) if isinstance(line, str) else line
        if ln.reading is not None:
            raise ValueError(f"line {ln.id} has a reading already")
        ln.reading = Reading(annotator=annotator, text=text, confidence=confidence, words=list(words),
                             alternatives=list(alternatives), output=output, **fields)
        return ln.reading

    # ------------------------------------------------------------------ resolving
    def line(self, line_id: str) -> Line | None:
        return next((ln for ln in self.lines if ln.id == line_id), None)

    def line_ranks(self) -> dict[str, int]:
        """Line id -> its rank on the page by the reading order; lines the order leaves out after those, in list
        order."""
        o = self.order("lines")
        ranks: dict[str, int] = {lid: i for i, lid in enumerate(o.lines)} if o is not None else {}
        for ln in self.lines:
            ranks.setdefault(ln.id, len(ranks))
        return ranks

    def rows(self) -> dict[str, int]:
        """Line id -> its visual row within its region, by the reading order (lines it leaves out: none)."""
        o = self.order("lines")
        return dict(zip(o.lines, o.rows)) if o is not None else {}

    def ordered_lines(self) -> list[Line]:
        ranks = self.line_ranks()
        return sorted(self.lines, key=lambda ln: ranks[ln.id])

    def lines_of(self, region_id: str | None) -> list[Line]:
        """The lines assigned to a region (``None``: to none), in reading order."""
        return [ln for ln in self.ordered_lines() if ln.region == region_id]

    def table(self, target: Ref) -> Table | None:
        return next((tb for tb in reversed(self.tables) if tb.target == target), None)

    def formula(self, target: Ref) -> Formula | None:
        return next((f for f in reversed(self.formulas) if f.target == target), None)

    def edit(self, target: Ref, kinds: Iterable[str]) -> str | None:
        """The text of the latest edit of ``target`` among ``kinds`` (in ``EDITS`` order: a later kind wins), or
        ``None`` when there is none."""
        kinds = tuple(kinds)
        best = None
        for e in self.edits:
            if e.target == target and e.kind in kinds:
                if best is None or EDITS.index(e.kind) >= EDITS.index(best.kind):
                    best = e
        return best.text if best is not None else None

    def text_of(self, line: Line, kinds: Iterable[str] = ("nfc",)) -> str | None:
        """A line's text with the latest of ``kinds`` edits applied; ``None`` until it was read."""
        if line.reading is None:
            return None
        edited = self.edit(line.id, kinds)
        return edited if edited is not None else line.reading.text

    # ------------------------------------------------------------------ derived
    @property
    def text(self) -> str:
        """The page's text as written (NFC), as laid out, full page: the read lines in reading order, one per line;
        a region with a table structure is written as a Markdown table instead of its lines (an HTML table when a
        cell spans); regions the default policy puts nowhere (removed, suppressed, duplicate) left out."""
        from .policy import DEFAULT_POLICY
        tables = {tb.target: tb for tb in self.tables if tb.cells}
        hidden = {r.id for r in self.regions if DEFAULT_POLICY.layer_of(self, r.id) == "none"}
        out, done = [], set()
        for ln in self.ordered_lines():
            if ln.region in hidden:
                continue
            if ln.region in tables:
                if ln.region not in done:
                    done.add(ln.region)
                    out.append(render_table(tables[ln.region]))
            else:
                text = self.text_of(ln)
                if text is not None:
                    out.append(text)
        return "\n".join(out)

    @property
    def confidence(self) -> float | None:
        """Mean reading confidence, weighted by length."""
        num = den = 0.0
        for ln in self.lines:
            r = ln.reading
            if r is not None and r.confidence is not None and r.text:
                num += r.confidence * len(r.text)
                den += len(r.text)
        return num / den if den else None


def render_table(table: Table, text=lambda c: c.text) -> str:
    """A table as a Markdown pipe table, first row as the header; as an HTML table when any cell spans rows or
    columns (Markdown cannot hold spans). ``text(cell)`` gives a cell's text (its own by default)."""
    cells = table.cells
    if any(c.row_span > 1 or c.col_span > 1 for c in cells):
        rows: dict[int, list] = {}
        for c in sorted(cells, key=lambda c: (c.start_row, c.start_col)):
            span = "".join(f' {k}span="{n}"' for k, n in (("row", c.row_span), ("col", c.col_span)) if n > 1)
            tag = "th" if c.column_header else "td"
            rows.setdefault(c.start_row, []).append(f"<{tag}{span}>{_html_escape(text(c))}</{tag}>")
        return "<table>" + "".join(f"<tr>{''.join(r)}</tr>" for _, r in sorted(rows.items())) + "</table>"
    n_rows = max((c.end_row for c in cells), default=0)
    n_cols = max((c.end_col for c in cells), default=0)
    grid = [[""] * n_cols for _ in range(n_rows)]
    for c in cells:
        grid[c.start_row][c.start_col] = " ".join(text(c).split()).replace("|", "\\|")
    lines = ["| " + " | ".join(row) + " |" for row in grid]
    if lines:
        lines.insert(1, "|" + "|".join("---" for _ in range(n_cols)) + "|")
    return "\n".join(lines)


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
