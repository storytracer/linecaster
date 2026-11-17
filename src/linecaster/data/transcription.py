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
from functools import lru_cache
from typing import Annotated, Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, model_validator

Point = list[float]
Box = list[float]               # [x, y, width, height]
Ref = str                       # a reference (linecaster.data.refs)

#: the format of a stored page record
SCHEMA = "linecaster.page/5"

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
                        "ordering", "image", "import"})


@lru_cache(maxsize=1)
def producer() -> str:
    """The linecaster that runs here: its release and, where known, its commit (``0.10.0 (1a2b3c4d5e6f)``, ``dirty``
    with uncommitted changes), as a data file names its writer."""
    from linecaster import __version__

    try:
        from linecaster.runtime.provenance import commit

        c = commit()
    except Exception:  # noqa: BLE001 - provenance is best effort
        c = None
    return __version__ + (f" ({c['commit'][:12]}{', dirty' if c.get('dirty') else ''})" if c else "")


class Annotator(_Model):
    """One thing that worked on an annotation set: a model step, a rule-based step, a delivered file, or people.
    ``measurements`` keys come from the fixed vocabulary ``linecaster.data.MEASUREMENTS``. ``linecaster``: the
    linecaster that recorded it (``producer``; set by ``Transcription.add_annotator``), so a record names its writer
    wherever it travels."""

    kind: Literal["model", "rule", "file", "human"] = "model"
    step: str                                # layout, lines, recognition, ..., unicode, typography; transcription
    name: str                                # the model; without one, what ran; for people, the group
    engine: str | None = None                # the engine's code id, e.g. kraken.recognition.v1
    revision: str | None = None
    preset: str | None = None                # the catalog preset it ran as (id@edition before linecaster 0.10)
    preset_sha256: str | None = None
    conventions: str | None = None           # an importer's conventions, resolved: their chain, a>b>c
    conventions_sha256: str | None = None    # the resolved conventions' content
    recipe: str | None = None                # the recipe the run followed (id@edition before 0.10)
    recipe_sha256: str | None = None
    backend: str | None = None               # in-process or served (with the server's address)
    run: str | None = None                   # the run id (RunRecord.run_id)
    linecaster: str | None = None            # the linecaster that recorded it (producer())
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
    format: str | None = None                # alto, page, hocr, html, mediawiki, text, markdown, ...
    uri: str | None = None
    sha256: str | None = None                # of the delivered file
    dataset: str | None = None               # repo@revision
    record: str | None = None                # the row or file the set was read from
    revision: str | None = None              # the revision of the source text that anchors refer to
    image_sha256: str | None = None          # the image the coordinates refer to
    image_width: int | None = None
    image_height: int | None = None
    scale: list[float] | None = None         # [sx, sy] the set was scaled by (AnnotationSet.scaled)
    # the normalizations a ground truth's transcription already embodies (its conventions: ſ written s, divided
    # words joined within a page, ...), catalog ids; scoring checks a lane against them
    normalized: list[str] = Field(default_factory=list)


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
    """How characters ``charspan`` of a reading's text are set: bold, italic, underlined, struck through, raised or
    lowered."""

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


class Anchor(_Model):
    """Where a zone's text comes from in the source the set was read from: characters ``[start, end)`` of the source
    text (``Source.uri`` / ``Source.record`` at ``Source.revision``)."""

    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self):
        if self.end < self.start:
            raise ValueError(f"anchor ends before it starts: [{self.start}, {self.end})")
        return self


class Zone(Annotation):
    """A place on the page image an annotator found, or, read from a source text, a block or line of it (then
    ``anchor`` says where in the source it comes from). ``id`` never contains ``#``, ``/`` or ``[``."""

    id: str
    box: Box | None = None
    polygon: list[Point] | None = None
    parent: str | None = None                # the zone it lies in
    anchor: Anchor | None = None


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
    """One cell of a table: its rows and columns (offsets, end exclusive), its text and whether it heads a column, a
    row or a section. ``formulas``: where the source marks a formula in the cell (MathML, a wiki's ``<math>``), its
    character span in ``text`` ([start, end), the ``$…$`` the text writes it as included); a ``$`` outside them is
    printed. Empty where the source marks none or cannot say (an engine's HTML that writes ``$…$`` as text)."""

    start_row: int
    end_row: int
    start_col: int
    end_col: int
    text: str = ""
    column_header: bool = False
    row_header: bool = False
    row_section: bool = False
    formulas: list[list[int]] = Field(default_factory=list)

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
    source: str | None = Field(None, description="the LaTeX as the source wrote it, where the reading's differs "
                                                 "(a wiki's formula as its software normalizes it)")


#: the property schemes: yes/no classifications of what content is like (a tagger's, ``linecaster.engines.tagging``),
#: each defined by its vocabulary in the catalog (``vocabularies/<scheme>.yaml``)
PROPERTIES = ("degraded", "tiny", "rotated", "multi_column", "form")
#: classification schemes
SCHEMES = ("role", "production", "heading_level", "language", "script", "direction", "status", "picture_class",
           "code_language", *PROPERTIES)
STATUSES = ("illegible", "gap", "suppressed", "duplicate", "removed")
#: why something present in a source is not text of the page (a ``status`` classification's ``reason``)
REASONS: dict[str, str] = {
    "hidden": "a reader does not see it and it takes no space",
    "invisible": "a reader does not see it but it takes its space; a space or line break stays",
    "generated": "the source's software or markup draws it; the page does not print it",
    "editorial": "the source's editors wrote it; the page does not print it",
    "error": "a message of the source's software",
    "metadata": "markup that is not content: style sheets, scripts, metadata elements",
    "apparatus": "the source's notation for something the page prints differently, such as a footnote mark",
    "elsewhere": "printed text that belongs to another page or place",
    "layout": "markup that only arranges the page, such as an empty table row",
}


class Classification(Annotation):
    """One value of one scheme for one target; a ``status`` may say why (``reason``, one of ``REASONS``)."""

    target: Ref
    scheme: str
    value: str
    reason: str | None = None

    @model_validator(mode="after")
    def _reason(self):
        if self.reason is not None and (self.scheme != "status" or self.reason not in REASONS):
            raise ValueError(f"reason {self.reason!r}: only a status has one, from {sorted(REASONS)}")
        return self


class Description(Annotation):
    """Text an annotator wrote about a zone that is not on the page (a description of a picture, a summary)."""

    target: Ref
    kind: str = "description"                # description | data | note
    text: str
    format: str = "text"                     # text | markdown | html


#: edit kinds, in the order a text's forms are made
#: the edits a source states (since linecaster.page/5 only these: what linecaster derives, NFC or a normalization,
#: is a strategy's, applied when a text is written): its corrections, a word divided across lines or pages as
#: the whole word (``joined``), its expansions and regularizations
EDITS = ("joined", "corrected", "expanded", "regularized")


class Edit(Annotation):
    """Another form of a target's text, as the source states it; the target's own text (the literal) stays."""

    target: Ref
    kind: Literal["corrected", "joined", "expanded", "regularized"]
    text: str


#: link kinds: ``source`` is ``target``'s caption, note; continues it (a paragraph or footnote from an earlier
#: column or page); runs on into it; refers to it; is part of it (a line moved into another region by a later
#: step: the line's region is the latest ``part_of`` target, else ``Line.region``; a drop capital's region, part of
#: the line it begins: a document writes its letter there)
LINKS = ("caption_of", "note_of", "continues", "runs_into", "refers_to", "part_of")


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
    # (a division mark is no decision of a recomposition since linecaster.page/5: a strategy resolves it when a text
    # is written, linecaster.catalog normalizations divided-words and unicode-marks)
    # a new paragraph starts at this row: it is indented, a gap of about a blank line is above it, or (justified
    # text) the row before stopped short of the end margin
    "paragraph_break": ("indent", "gap", "short_row"),
    # the paragraph runs on into the next one (the next region, or the next page): it ends with a division
    # mark, or its last row reaches the end margin, without sentence-final punctuation
    "continuation": ("division_mark", "end_margin"),
}


class Decision(_Model):
    """One decision of a recomposition, at one row of a paragraph (``row``: the index into ``Paragraph.rows``): where
    a paragraph breaks, and where it runs on (what joins the pieces is the output strategy's, ``flow``)."""

    kind: Literal["paragraph_break", "continuation"]
    reason: str
    row: int = 0

    @model_validator(mode="after")
    def _reason(self):
        if self.reason not in DECISIONS[self.kind]:
            raise ValueError(f"{self.kind}: reason {self.reason!r} is none of {DECISIONS[self.kind]}")
        return self


class ParagraphRow(_Model):
    """One visual row of a paragraph: every line on the row."""

    lines: list[str]


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
    """The bottom range: the rows of lines a recomposition found to be one paragraph, with the decisions that made it.
    Its text is not stored (the lines' readings are): a strategy writes it (``literal``: the rows as laid out;
    ``flow``: joined into running text)."""

    kind: Literal["paragraph"] = "paragraph"
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
        """Appends ``annotator`` (naming the linecaster that records it, unless it names one) and returns its index,
        which its annotations name."""
        if annotator.linecaster is None:
            annotator.linecaster = producer()
        self.annotators.append(annotator)
        return len(self.annotators) - 1

    def add_output(self, output: RawOutput) -> int:
        self.outputs.append(output)
        return len(self.outputs) - 1

    def add_region(self, annotator: int, id: str, box: Box | None = None, polygon: list[Point] | None = None,
                   label: str = "", role: str | None = None, heading_level: int | None = None, **fields) -> Region:
        """Appends a region and, with ``role`` (a content role or a region label), its ``role`` classification
        (and a ``heading_level`` one), all by ``annotator``."""
        from linecaster.data.policy import classify_label
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
        """Adds a classification; a ``language``, ``script`` or ``direction`` that is none
        (``linecaster.data.writing.check``), and a property scheme's value other than ``yes`` or ``no``
        (``PROPERTIES``), is a ``ValueError``."""
        from linecaster.data.writing import check

        if scheme in PROPERTIES and str(value) not in ("yes", "no"):
            raise ValueError(f"{scheme} is a property scheme: its values are yes and no, not {value!r}")
        c = Classification(annotator=annotator, target=target, scheme=scheme, value=check(scheme, str(value)),
                           **fields)
        self.classifications.append(c)
        return c

    # ------------------------------------------------------------------ resolving
    def region(self, region_id: str) -> Region | None:
        return next((r for r in self.regions if r.id == region_id), None)

    def written(self, target: Ref, scheme: str) -> str | None:
        """A ``language``, ``script`` or ``direction`` of ``target`` as recorded on it or on what encloses it: a span
        or a word of a line falls back to its line, a line to its region (``region_of``), a region to the regions it
        lies in (``Zone.parent``), anything to the page (``""``). ``None`` where nothing records one: a value is never
        guessed here (``linecaster.text.scripts`` infers one from a text)."""
        from linecaster.data.refs import parse

        seen = set()
        while target not in seen:
            seen.add(target)
            value = self.classification(target, scheme)
            if value is not None:
                return value
            if target == "":
                return None
            ref = parse(target)
            if ref.page is not None:
                return None
            if ref.span is not None or ref.word is not None or ref.cell is not None:
                target = ref.id
                continue
            ln = self.line(ref.id) if hasattr(self, "line") else None
            if ln is not None:
                target = self.region_of(ln) or ""
                continue
            r = self.region(ref.id)
            target = r.parent if r is not None and r.parent else ""
        return None

    def language(self, target: Ref = "") -> str | None:
        """The language (BCP 47) recorded on ``target`` or what encloses it (``written``)."""
        return self.written(target, "language")

    def script(self, target: Ref = "") -> str | None:
        """The script (ISO 15924) recorded on ``target`` or what encloses it (``written``)."""
        return self.written(target, "script")

    def direction(self, target: Ref = "") -> str | None:
        """The writing direction (``linecaster.data.writing.DIRECTIONS``) recorded on ``target`` or what encloses it
        (``written``)."""
        return self.written(target, "direction")

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
        """The region label of a region, from its content role (``linecaster.data.policy.region_label``)."""
        from linecaster.data.policy import region_label
        return region_label(self, target)

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
        """The paragraphs of the latest annotator that made any (a second recomposition's replace the first's)."""
        found = [r for r in self.ranges if isinstance(r, Paragraph)]
        if not found:
            return []
        latest = max(p.annotator for p in found)
        return [p for p in found if p.annotator == latest]

    def link(self, source: Ref, kind: str) -> Ref | None:
        """The target of the latest link of ``kind`` from ``source``."""
        return next((ln.target for ln in reversed(self.links) if ln.source == source and ln.kind == kind), None)

    def range(self, range_id: str) -> Range | None:
        return next((r for r in self.ranges if r.id == range_id), None)

    @property
    def objects(self) -> dict[str, list]:
        """Regions in the shape of a Hugging Face ``objects`` column: ``bbox`` and ``category`` (the region label)
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

    def hidden_lines(self) -> set[str]:
        """The ids of lines whose own status puts them nowhere under the default policy (``duplicate``,
        ``removed``, ``suppressed``)."""
        from linecaster.data.policy import DEFAULT_POLICY
        return {c.target for c in self.classifications
                if c.scheme == "status" and DEFAULT_POLICY.layer(None, status=c.value) == "none"
                and self.line(c.target) is not None}

    def ordered_lines(self, hidden: bool = False) -> list[Line]:
        """The lines in reading order; without ``hidden``, lines whose status puts them nowhere left out."""
        ranks = self.line_ranks()
        skip = set() if hidden else self.hidden_lines()
        return sorted((ln for ln in self.lines if ln.id not in skip), key=lambda ln: ranks[ln.id])

    def region_of(self, line: Line | str) -> str | None:
        """The region a line belongs to: the latest ``part_of`` link's target, else the one it was assigned."""
        ln = self.line(line) if isinstance(line, str) else line
        return self.link(ln.id, "part_of") or ln.region

    def lines_of(self, region_id: str | None) -> list[Line]:
        """The lines that belong to a region (``None``: to none; ``region_of``), in reading order."""
        return [ln for ln in self.ordered_lines() if self.region_of(ln) == region_id]

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

    def text_of(self, line: Line, kinds: Iterable[str] = ()) -> str | None:
        """A line's text: its reading as recognized or transcribed (the literal), or with ``kinds`` the latest of
        those edits the source states for the whole line; ``None`` until it was read. Edits of a span of the line
        are a strategy's to apply (``linecaster.document.strategy``)."""
        if line.reading is None:
            return None
        edited = self.edit(line.id, kinds) if kinds else None
        return edited if edited is not None else line.reading.text

    # ------------------------------------------------------------------ derived
    @property
    def text(self) -> str:
        """The page's literal text, as laid out, full page: the read lines in reading order, one per line;
        a region with a table structure is written as a Markdown table instead of its lines (an HTML table when a
        cell spans); regions the default policy puts nowhere (removed, suppressed, duplicate) left out."""
        from linecaster.data.policy import DEFAULT_POLICY
        tables = {tb.target: tb for tb in self.tables if tb.cells}
        hidden = {r.id for r in self.regions if DEFAULT_POLICY.layer_of(self, r.id) == "none"}
        out, done = [], set()
        for ln in self.ordered_lines():
            region = self.region_of(ln)
            if region in hidden:
                continue
            if region in tables:
                if region not in done:
                    done.add(region)
                    out.append(render_table(tables[region]))
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
