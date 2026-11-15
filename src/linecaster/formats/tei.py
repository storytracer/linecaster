"""TEI P5 -> transcription: ``from_tei`` reads one page of a TEI document (namespace ``http://www.tei-c.org/ns/1.0``,
or none; of a ``teiCorpus``, its first ``TEI``) into a transcription. It reads this subset of TEI P5, in the first of
three forms the document has:

1. **Diplomatic, with geometry** (``sourceDoc``): a page is a ``surface`` (in document order, also inside
   ``surfaceGrp``); its ``zone`` elements are regions and its ``line`` elements (and ``zone[@type='line']``) lines,
   each with its coordinates (``@points``, else ``@ulx @uly @lrx @lry``; a ``path`` in a line its baseline). A
   ``zone``'s role comes from its ``@subtype``, else its ``@type`` (``ZONE_ROLES``; other names as PAGE-XML's and
   SegmOnto's region names read, ``linecaster.formats._xml.RAW_TO_LABEL``), else from the element that holds all its
   text (``fw``, ``note``, ``head``), else it is a paragraph. A ``zone`` of ``zone`` elements without lines or text of
   its own (a column of paragraphs) is no region; its ``zone`` elements are. A ``zone`` without lines holds its text
   as lines broken at ``lb``, without geometry. A line directly on the surface is a line without a region, unless all
   its text is in one ``fw``, ``note`` or ``head``: then it is a region of that role, with the line's geometry.
2. **Facsimile and text** (``facsimile`` and ``text``): the text read as in 3, with geometry where its elements
   point to a ``facsimile``'s ``zone`` (``@facs="#id"``): ``lb`` and ``l`` the line they begin, a block element
   (``p``, ``ab``, ``head``, ``fw``, ``note``, ``figure``, ...) its region; ``pb[@facs]`` names the page's ``surface``
   (else the surface of the page's number, where there is one).
3. **Text without geometry** (``text``: ``front``, ``body``, ``back``): blocks are regions (``p``, ``ab``, ``lg``,
   ``byline``, ``dateline``, ``signed``, ``trailer``, ... paragraphs; ``head`` a heading, its level the number of
   ``div`` around it; ``titlePart`` the title; ``item`` a list item; ``fw`` the page's furniture; ``note`` a note;
   ``figure`` a picture, its ``head`` and ``p`` captions linked to it, its ``figDesc`` its description; ``table`` a
   table, a line per ``row``); ``lb`` begins a line, and so does ``l`` (a verse line); ``cb`` ends a block. Lines
   have no geometry, as the text importer's.

**Pages.** A ``sourceDoc`` page is a surface; in a text, ``pb`` begins a page (text before the first ``pb``, where
there is any, is a page of its own). The reader reads one page: ``page``, a number (1-based) or the ``xml:id`` of the
page's ``surface`` or ``pb``; by default the first.

**Furniture and notes.** ``fw`` is the page's furniture by its ``@type``: ``header`` (and ``running-title`` and
the like) a header, ``pageNum`` a page number, ``catch`` a catchword, ``sig`` a signature mark, ``footer`` a footer;
another type a header above the page's first text and a footer below it. A ``note`` is a footnote, a marginal note
(``@place`` ``margin``, ``left``, ``right``, ...) marginalia, ``@place="end"`` an endnote; in a text, a note inside a
block is a region of its own after that block, linked to it (``note_of``), and furniture comes first (above the
page's first text) or last (below it), as the HTML importer orders them.

**Inline markup**, in the lines of every form:

- ``choice``: the source's reading is the line's text, with the other as an edit of its span, as the HTML importer
  records a source's edits: ``sic`` with ``corr`` a ``corrected`` edit, ``abbr`` with ``expan`` an ``expanded`` one,
  ``orig`` with ``reg`` a ``regularized`` one; another ``choice`` its first child; ``app`` its ``lem`` (else its first
  ``rdg``);
- ``unclear``: its text kept, its span with status ``illegible`` (scoring writes it as U+FFFD, as it does every
  illegible span); ``gap``: nothing in the text, a ``status`` ``gap`` on the empty span where it stands;
- ``@rend`` (on ``hi`` and any other element): ``italic``, ``bold``, ``underline``, ``strikethrough``, ``sup``,
  ``sub`` and their usual spellings as the reading's formatting;
- ``lb[@break='no']``: the word divided there, its two halves (the last word of one line, the first of the next) each
  with a ``joined`` edit holding the whole word (the first half without its division mark), as ALTO's divided words
  are read;
- ``space`` a space.

**Writing.** ``xml:lang`` is a ``language`` classification (``linecaster.data.writing.language_tag``; an ill-formed
value is skipped) on the narrowest target it holds for, where it differs from what encloses it: the page (the
language of ``TEI``, ``text`` and ``body``, or of ``TEI``, ``sourceDoc`` and the surface), a region, a line (a
``line`` or ``l`` element), or a span of a line for inline elements.

Anything else: its text kept, the element ignored (``teiHeader``, ``figDesc``, ``desc`` and the like hold no text of
the page); an unknown element never fails the import.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ..data.transcription import Description, Edit, Formatting, Link, Source, Transcription
from ..data.writing import language_tag
from . import _xml as X


#: a zone's ``@type`` or ``@subtype``, lower-cased without punctuation -> the content role
ZONE_ROLES = {
    **dict.fromkeys(("column", "paragraph", "para", "p", "ab", "main", "maintext", "body", "text", "textblock",
                     "textregion", "block"), "paragraph"),
    **dict.fromkeys(("head", "heading", "subheading", "sectionheading"), "heading"),
    **dict.fromkeys(("title", "titlepart"), "title"),
    **dict.fromkeys(("header", "runninghead", "runningheader", "runningtitle", "pageheader", "fwheader"), "header"),
    **dict.fromkeys(("footer", "pagefooter", "runningfoot", "fwfooter"), "footer"),
    **dict.fromkeys(("pagenum", "pagenumber", "pageno", "folio", "foliation", "pagination", "numbering",
                     "number"), "page_number"),
    **dict.fromkeys(("catch", "catchword"), "catch_word"),
    **dict.fromkeys(("sig", "signature", "signaturemark"), "signature_mark"),
    **dict.fromkeys(("marginalia", "margin", "marginal", "marginnote", "sidenote", "gloss"), "marginalia"),
    **dict.fromkeys(("note", "footnote"), "footnote"),
    "endnote": "endnote",
    **dict.fromkeys(("figure", "illustration", "graphic", "image", "picture", "ornament", "decoration"), "picture"),
    "table": "table",
    **dict.fromkeys(("caption", "figdesc", "legend"), "caption"),
    **dict.fromkeys(("list", "item", "listitem"), "list_item"),
}
#: ``fw/@type``, lower-cased without punctuation -> the content role (the page's furniture)
FW_ROLES = {
    **dict.fromkeys(("header", "head", "runninghead", "runningheader", "runningtitle", "pageheader"), "header"),
    **dict.fromkeys(("footer", "foot", "runningfoot", "pagefooter"), "footer"),
    **dict.fromkeys(("pagenum", "pagenumber", "pageno", "folio", "number"), "page_number"),
    **dict.fromkeys(("catch", "catchword"), "catch_word"),
    **dict.fromkeys(("sig", "signature", "signaturemark"), "signature_mark"),
}
#: ``note/@place`` -> the content role (a note without one is a footnote)
NOTE_PLACES = {
    **dict.fromkeys(("foot", "bottom", "below"), "footnote"),
    **dict.fromkeys(("margin", "margin-left", "margin-right", "left", "right", "inner", "outer", "inside", "outside",
                     "marginal", "opposite"), "marginalia"),
    "end": "endnote",
}
#: ``@rend`` words -> the formatting they set
REND = {
    **dict.fromkeys(("italic", "italics", "i", "it", "slanted", "oblique"), "italic"),
    **dict.fromkeys(("bold", "b", "bf", "strong"), "bold"),
    **dict.fromkeys(("underline", "underlined", "u", "ul"), "underline"),
    **dict.fromkeys(("strikethrough", "strike", "struck", "line-through", "linethrough", "overstrike"),
                    "strikethrough"),
    **dict.fromkeys(("sup", "super", "superscript"), "super"),
    **dict.fromkeys(("sub", "subscript"), "sub"),
}
#: ``choice``'s pairs: the source's reading, the other, the edit kind
PAIRS = (("sic", "corr", "corrected"), ("abbr", "expan", "expanded"), ("orig", "reg", "regularized"))
#: elements that hold no text of the page
SKIPPED = frozenset({"teiHeader", "facsimile", "sourceDoc", "standOff", "figDesc", "desc", "interp", "interpGrp",
                     "certainty", "respons", "index", "graphic", "binaryObject"})
#: block elements of a text -> their role
BLOCKS = {
    **dict.fromkeys(("p", "ab", "lg", "byline", "dateline", "docImprint", "docEdition", "signed", "salute",
                     "trailer", "speaker", "stage"), "paragraph"),
    "head": "heading", "titlePart": "title", "item": "list_item",
}
#: elements of a text that only hold blocks
CONTAINERS = frozenset({"text", "front", "body", "back", "group", "div", "div1", "div2", "div3", "div4", "div5",
                        "div6", "div7", "titlePage", "docTitle", "list", "listBibl", "opener", "closer", "epigraph",
                        "argument", "floatingText", "sp", "postscript", "castList"})
#: division marks a divided word's first half may end with (left out of the whole word)
DIVISION_MARKS = "-­‐¬⸗="
#: roles a region keeps without text
TEXTLESS = frozenset({"picture", "table"})


@dataclass
class _Run:
    text: str
    fmt: frozenset = frozenset()
    edit: tuple | None = None          # (kind, the other reading, serial)
    language: str | None = None
    status: tuple | None = None        # ("illegible" | "gap", serial)
    within: str | None = None          # in a line of a sourceDoc: the role of an fw, note or head around it


@dataclass
class _Break:
    """The beginning of a line: its id, geometry, its own language (a ``line`` or ``l``), and whether it continues
    the word the line before ends with (``lb[@break='no']``)."""

    id: str | None = None
    polygon: list | None = None
    box: list | None = None
    baseline: list | None = None
    language: str | None = None
    joins: bool = False


@dataclass
class _Block:
    """A region being read (``role`` None: lines without a region): its runs and line breaks (``items``), and the
    notes and captions that go after it."""

    role: str | None
    raw: str = ""
    id: str | None = None
    polygon: list | None = None
    box: list | None = None
    heading_level: int | None = None
    language: str | None = None
    part: str = "body"
    items: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    captions: list = field(default_factory=list)
    description: str | None = None

    def has_text(self) -> bool:
        return any(isinstance(r, _Run) and (r.text.strip() or r.status) for r in self.items)


class _Grid:
    """A surface's coordinates in pixels of its image: its origin (``@ulx``, ``@uly``) and the scale to the size its
    ``graphic`` states."""

    def __init__(self, ox: float = 0.0, oy: float = 0.0, sx: float = 1.0, sy: float = 1.0):
        self.ox, self.oy, self.sx, self.sy = ox, oy, sx, sy

    def points(self, pts):
        return [[(x - self.ox) * self.sx, (y - self.oy) * self.sy] for x, y in pts]


class _Done(Exception):
    """The page that is read has ended."""


def _key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _length(value: str | None) -> float | None:
    """A ``graphic``'s ``@width`` or ``@height`` in pixels (``2480px``, ``2480``); None in other units."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:px)?\s*", value or "")
    return float(m.group(1)) if m else None


def _surface(surface) -> tuple[_Grid, int | None, int | None, str | None]:
    """A surface's grid, its image's size and its image's URL (its ``graphic``)."""
    ulx, uly, lrx, lry = (X.parse_num(surface.get(k)) for k in ("ulx", "uly", "lrx", "lry"))
    ox, oy = ulx or 0.0, uly or 0.0
    w = lrx - ox if lrx is not None else None
    h = lry - oy if lry is not None else None
    g = X.child(surface, "graphic")
    gw, gh = (_length(g.get("width")), _length(g.get("height"))) if g is not None else (None, None)
    grid = _Grid(ox, oy, gw / w if gw and w else 1.0, gh / h if gh and h else 1.0)
    width, height = gw or w, gh or h
    return (grid, round(width) if width else None, round(height) if height else None,
            (g.get("url") or None) if g is not None else None)


def _coords(el, grid: _Grid) -> tuple[list | None, list | None]:
    """An element's polygon (``@points``) and box (the polygon's bounds, else ``@ulx @uly @lrx @lry``)."""
    pts = X.parse_points(el.get("points"))
    if pts:
        pts = grid.points(pts)
        return pts, X.bounds(pts)
    ulx, uly, lrx, lry = (X.parse_num(el.get(k)) for k in ("ulx", "uly", "lrx", "lry"))
    if None in (ulx, uly, lrx, lry):
        return None, None
    (x0, y0), (x1, y1) = grid.points([[ulx, uly], [lrx, lry]])
    return None, [x0, y0, x1 - x0, y1 - y0]


def _formats(rend: str | None) -> frozenset:
    return frozenset(REND[w] for w in re.split(r"[\s,;:()]+", (rend or "").lower()) if w in REND)


def _scope(el, ctx: dict) -> dict:
    """``ctx`` with what ``el`` says of its text: its language (``xml:lang``) and its formatting (``@rend``)."""
    tag = language_tag(el.get("lang"))
    if tag and tag != ctx["language"]:
        ctx = {**ctx, "language": tag}
    f = _formats(el.get("rend"))
    if f - ctx["fmt"]:
        ctx = {**ctx, "fmt": ctx["fmt"] | f}
    return ctx


def _fw_role(el, printed: bool) -> str:
    return FW_ROLES.get(_key(el.get("type"))) or ("footer" if printed else "header")


def _note_role(el) -> str:
    for p in (el.get("place") or "").lower().split():
        if p in NOTE_PLACES:
            return NOTE_PLACES[p]
    return {"endnote": "endnote", "marginal": "marginalia", "marginalia": "marginalia",
            "sidenote": "marginalia"}.get(_key(el.get("type")), "footnote")


def _heading_level(el) -> int:
    return max(1, sum(1 for a in el.iterancestors() if isinstance(a.tag, str) and re.fullmatch(r"div\d?", a.tag)))


def _is_line(el) -> bool:
    return el.tag == "line" or (el.tag == "zone" and _key(el.get("type")) in ("line", "textline"))


class _Walk:
    """One walk over a text (``lines_given`` False: blocks, line breaks and pages from the markup) or over the lines
    and zones of a surface (``lines_given``: the lines are given, ``fw``, ``note`` and ``head`` inside them only say
    what their text is)."""

    def __init__(self, geometry=None, target: int = 0, start: int = 0, lines_given: bool = False):
        self.geometry = geometry or (lambda el: None)   # an element -> its facs zone's (polygon, box), or None
        self.target, self.page = target, start
        self.lines_given = lines_given
        self.zone_text = False                         # reading a zone's text: lb breaks lines
        self.blocks: list[_Block] = []
        self.cur: _Block | None = None
        self.pb = None                                 # the page's pb
        self.printed = False                           # the page's body has printed text
        self.serial = 0
        self.language: str | None = None               # the language of the block-level element being read
        self.line_text = False                         # the line being read has text (lines given)
        self.join_next = False                         # the next line continues this one's last word

    @property
    def on(self) -> bool:
        return self.page == self.target

    def next(self) -> int:
        self.serial += 1
        return self.serial

    # -- blocks
    def begin(self, el, role: str, ctx: dict, part: str = "body", level: int | None = None) -> None:
        if not self.on:
            return
        polygon, box = self.geometry(el) or (None, None)
        self.cur = _Block(role, raw=el.get("type") or el.tag, id=el.get("id"), polygon=polygon, box=box,
                          heading_level=level, language=ctx["language"], part=part)

    def block(self) -> _Block:
        if self.cur is None:
            self.cur = _Block("paragraph", language=self.language)
        return self.cur

    def flush(self) -> None:
        b, self.cur = self.cur, None
        if b is None or not self.on:
            return
        if b.has_text() or b.role in TEXTLESS:
            self.blocks.append(b)
        else:                                          # an empty block: its notes stay, as blocks of their own
            self.blocks += b.notes

    def emit(self, text: str, ctx: dict) -> None:
        if not self.on or (not text and not ctx["status"]):
            return
        b = self.block()
        b.items.append(_Run(text, ctx["fmt"], ctx["edit"], ctx["language"], ctx["status"], ctx["within"]))
        if text.strip():
            self.line_text = True
            if b.part == "body" and ctx["within"] is None and b.role not in ("header", "footer", "page_number",
                                                                             "catch_word", "signature_mark"):
                self.printed = True

    def line_break(self, el, ctx: dict, joins: bool = False, language: str | None = None) -> None:
        if not self.on:
            return
        polygon, box = (self.geometry(el) if el is not None else None) or (None, None)
        self.block().items.append(_Break(el.get("id") if el is not None else None, polygon, box, None, language,
                                         joins))

    # -- the walk
    def children(self, el, ctx: dict) -> None:
        if el.text:
            self.emit(el.text, ctx)
        for c in el:
            self.element(c, ctx)
            if c.tail:
                self.emit(c.tail, ctx)

    def element(self, el, ctx: dict) -> None:
        tag = el.tag
        if not isinstance(tag, str) or tag in SKIPPED:
            return
        ctx = _scope(el, ctx)
        if tag == "pb":
            if not self.lines_given:
                self.page_break(el)
            return
        if self.inline(el, ctx):
            return
        if self.lines_given:
            self.in_line(el, ctx)
            return
        if tag == "lb":
            self.line_break(el, ctx, joins=el.get("break") == "no")
        elif tag == "l":
            self.line_break(el, ctx, language=ctx["language"])
            self.children(el, ctx)
            self.line_break(None, ctx)
        elif tag == "cb":
            self.flush()
        elif tag == "fw":
            self.aside(el, ctx, _fw_role(el, self.printed), standing=True)
        elif tag == "note":
            self.aside(el, ctx, _note_role(el), standing=self.cur is None or not self.cur.has_text())
        elif tag == "figure":
            self.figure(el, ctx)
        elif tag == "table":
            self.table(el, ctx)
        elif tag in BLOCKS:
            self.as_block(el, BLOCKS[tag], ctx, _heading_level(el) if tag == "head" else None)
        elif tag in CONTAINERS:
            self.flush()
            saved, self.language = self.language, ctx["language"]
            self.children(el, ctx)
            self.flush()
            self.language = saved
        else:                                          # anything else: its text kept
            self.children(el, ctx)

    def inline(self, el, ctx: dict) -> bool:
        """Reads the inline markup every form shares; False: ``el`` is none of it."""
        tag = el.tag
        if tag == "choice":
            kids: dict = {}
            for c in el:
                if isinstance(c.tag, str):
                    kids.setdefault(c.tag, c)
            for printed, other, kind in PAIRS:
                if printed in kids and other in kids:
                    text = " ".join("".join(kids[other].itertext()).split())
                    inner = _scope(kids[printed], ctx)
                    self.children(kids[printed], {**inner, "edit": (kind, text, self.next())} if text else inner)
                    return True
            first = next((c for c in el if isinstance(c.tag, str)), None)
            if first is not None:
                self.element(first, ctx)
            return True
        if tag == "app":
            lem = X.child(el, "lem")
            first = lem if lem is not None else X.child(el, "rdg")
            if first is not None:
                self.element(first, ctx)
            return True
        if tag == "gap":
            self.emit("", {**ctx, "status": ("gap", self.next())})
            return True
        if tag == "unclear":
            self.children(el, {**ctx, "status": ("illegible", self.next())})
            return True
        if tag == "space":
            self.emit(" ", ctx)
            return True
        return False

    def in_line(self, el, ctx: dict) -> None:
        """An element in a given line or a zone's text: ``fw``, ``note`` and ``head`` say what their text is."""
        tag = el.tag
        if tag == "lb":
            if self.zone_text:
                self.line_break(el, ctx, joins=el.get("break") == "no")
            elif el.get("break") == "no":
                if self.line_text:
                    self.join_next = True
                elif self.cur is not None:
                    breaks = [b for b in self.cur.items if isinstance(b, _Break)]
                    if breaks:
                        breaks[-1].joins = True
            return
        if tag in ("zone", "line"):                    # read by the surface's walk
            return
        within = {"fw": lambda: _fw_role(el, self.printed), "note": lambda: _note_role(el),
                  "head": lambda: "heading"}.get(tag)
        self.children(el, {**ctx, "within": within()} if within else ctx)

    def page_break(self, el) -> None:
        self.flush()
        self.page += 1
        if self.page > self.target:
            raise _Done
        if self.on:
            self.pb, self.printed = el, False

    def aside(self, el, ctx: dict, role: str, standing: bool) -> None:
        """A block read apart from the one being read: furniture (header above the page's first text, else footer),
        or a note (standing: a block of the body; else after the block it stands in)."""
        saved, self.cur = self.cur, None
        part = ("footer" if self.printed else "header") if el.tag == "fw" else "body"
        self.begin(el, role, ctx, part)
        self.children(el, ctx)
        b, self.cur = self.cur, saved
        if b is None or not self.on or not b.has_text():
            return
        if standing or saved is None:
            self.blocks.append(b)
        else:
            saved.notes.append(b)

    def as_block(self, el, role: str, ctx: dict, level: int | None = None) -> None:
        self.flush()
        saved, self.language = self.language, ctx["language"]
        self.begin(el, role, ctx, level=level)
        self.children(el, ctx)
        self.flush()
        self.language = saved

    def figure(self, el, ctx: dict) -> None:
        self.flush()
        if not self.on:
            return
        self.begin(el, "picture", ctx)
        pic, self.cur = self.cur, None
        self.blocks.append(pic)
        for c in el:
            if not isinstance(c.tag, str):
                continue
            if c.tag == "figDesc":
                text = " ".join("".join(c.itertext()).split())
                pic.description = text or pic.description
            elif c.tag == "figure":
                self.figure(c, _scope(c, ctx))
            elif c.tag not in SKIPPED:
                self.begin(c, "caption", _scope(c, ctx))
                self.children(c, _scope(c, ctx))
                cap, self.cur = self.cur, None
                if cap.has_text():
                    pic.captions.append(cap)

    def table(self, el, ctx: dict) -> None:
        self.flush()
        if not self.on:
            return
        self.begin(el, "table", ctx)
        tb = self.cur
        for c in el:
            if not isinstance(c.tag, str):
                continue
            if c.tag == "head":
                self.cur = None
                self.begin(c, "caption", _scope(c, ctx))
                self.children(c, _scope(c, ctx))
                cap = self.cur
                if cap.has_text():
                    tb.captions.append(cap)
            elif c.tag == "row":
                self.cur = tb
                self.line_break(c, ctx)
                for k, cell in enumerate(x for x in c if isinstance(x.tag, str) and x.tag == "cell"):
                    if k:
                        self.emit(" ", ctx)
                    self.children(cell, _scope(cell, ctx))
        self.cur = tb
        self.flush()


# ---------------------------------------------------------------------------------------------- pages


def _lead(text_el, pb) -> bool:
    """Whether ``text_el`` has text before its first ``pb``."""
    for s in pb.xpath("preceding::text()"):
        if not s.strip():
            continue
        p = s.getparent()
        if p is not None and (p is text_el or any(a is text_el for a in p.iterancestors())):
            if not any(isinstance(a.tag, str) and a.tag in SKIPPED for a in (p, *p.iterancestors())):
                return True
    return False


def _page_index(pages: list, page: int | str, names) -> int:
    """The index of ``page`` (a number from 1, or an ``xml:id`` ``names(pages[i])`` gives) in ``pages``."""
    if isinstance(page, int) or str(page).strip().isdigit():
        k = int(page) - 1
        if 0 <= k < len(pages):
            return k
        raise ValueError(f"TEI: no page {page} (the document has {len(pages)})")
    for k, p in enumerate(pages):
        if page in names(p):
            return k
    raise ValueError(f"TEI: no page {page!r} (no surface or pb has that xml:id)")


def _surfaces(source_doc) -> list:
    return [s for s in source_doc.iter("surface")
            if not any(isinstance(a.tag, str) and a.tag == "surface" for a in s.iterancestors())]


def _surface_of(el):
    """The surface ``el`` is or lies in."""
    if el is None:
        return None
    return el if el.tag == "surface" else next((a for a in el.iterancestors() if a.tag == "surface"), None)


def _context(*els) -> dict:
    ctx = {"fmt": frozenset(), "edit": None, "language": None, "status": None, "within": None}
    for el in els:
        if el is not None:
            tag = language_tag(el.get("lang"))
            if tag:
                ctx = {**ctx, "language": tag}
    return ctx


# ---------------------------------------------------------------------------------------------- the forms


def _diplomatic(surface, grid: _Grid, ctx: dict) -> list[_Block]:
    """The blocks of a ``sourceDoc`` surface (form 1)."""
    w = _Walk(lines_given=True)
    out: list[_Block] = []

    def read_line(line, b: _Block, ctx: dict) -> None:
        lctx = _scope(line, ctx)
        polygon, box = _coords(line, grid)
        path = X.child(line, "path")
        baseline = grid.points(X.parse_points(path.get("points"))) if path is not None and X.parse_points(
            path.get("points")) else None
        b.items.append(_Break(line.get("id"), polygon, box, baseline, lctx["language"], w.join_next))
        w.cur, w.line_text, w.join_next, w.zone_text = b, False, False, False
        w.children(line, lctx)

    def role_of(el) -> tuple[str | None, str]:
        """A zone's role by its type or its element (None: by its text), and its raw label."""
        for attr in ("subtype", "type"):
            role = ZONE_ROLES.get(_key(el.get(attr)))
            if role:
                return role, el.get(attr)
        if el.tag == "fw":
            return _fw_role(el, w.printed), el.get("type") or "fw"
        if el.tag == "note":
            return _note_role(el), el.get("type") or "note"
        if el.tag in ("head", "figure", "table"):
            return {"head": "heading", "figure": "picture", "table": "table"}[el.tag], el.tag
        return None, el.get("type") or el.tag

    def uniform(b: _Block) -> str | None:
        found = {r.within for r in b.items if isinstance(r, _Run) and r.text.strip()}
        return found.pop() if len(found) == 1 else None

    def zone(z, ctx: dict) -> None:
        zctx = _scope(z, ctx)
        role, raw = role_of(z)
        polygon, box = _coords(z, grid)
        b = _Block(role, raw=raw, id=z.get("id"), polygon=polygon, box=box, language=zctx["language"])
        kids = [c for c in z if isinstance(c.tag, str)]
        later = [c for c in kids if c.tag in ("zone", "surface") and not _is_line(c)]
        if any(_is_line(c) for c in kids):
            for c in kids:
                if _is_line(c):
                    read_line(c, b, zctx)
        else:
            w.cur, w.zone_text, w.line_text = b, True, False
            w.children(z, zctx)
            w.zone_text = False
        w.cur = None
        lines = b.has_text()
        b.role = b.role or uniform(b) or (X.label_from_raw(z.get("type")) if z.get("type") else "paragraph")
        if lines or b.role in TEXTLESS or (not later and (polygon is not None or box is not None)):
            out.append(b)
        for c in later:
            zone(c, zctx)

    for c in surface:
        if not isinstance(c.tag, str) or c.tag in SKIPPED:
            continue
        if _is_line(c):
            b = _Block(None)
            read_line(c, b, ctx)
            w.cur = None
            role = uniform(b)
            if role is not None:                       # a line that is all furniture, a note or a heading
                brk = b.items[0]
                b.role, b.raw, b.polygon, b.box = role, "line", brk.polygon, brk.box
                out.append(b)
            elif out and out[-1].role is None:
                out[-1].items += b.items
            else:
                out.append(b)
        else:
            zone(c, ctx)
    return out


# ---------------------------------------------------------------------------------------------- building


def _lines(items: list) -> list[tuple[_Break, str, list[tuple[int, int, _Run]]]]:
    """A block's items as lines: (the break that begins it, its text with whitespace collapsed, (start, end, run)
    per run); empty lines left out."""
    segments, brk, cur = [], _Break(), []
    for it in items:
        if isinstance(it, _Break):
            segments.append((brk, cur))
            brk, cur = it, []
        else:
            cur.append(it)
    segments.append((brk, cur))
    out = []
    for brk, runs in segments:
        text, spans = "", []
        for r in runs:
            s = re.sub(r"\s+", " ", r.text)
            if (not text or text.endswith(" ")) and s.startswith(" "):
                s = s[1:]
            spans.append((len(text), len(text) + len(s), r))
            text += s
        if text.endswith(" "):
            text = text[:-1]
            spans = [(min(a, len(text)), min(e, len(text)), r) for a, e, r in spans]
        if text:
            out.append((brk, text, spans))
    return out


def _trim(text: str, a: int, e: int) -> tuple[int, int]:
    while a < e and text[a].isspace():
        a += 1
    while e > a and text[e - 1].isspace():
        e -= 1
    return a, e


def _grouped(spans, key) -> list[tuple[int, int, object]]:
    """Consecutive spans with one value of ``key`` (not None) as one: (start, end, value)."""
    out: list[list] = []
    for a, e, r in spans:
        v = key(r)
        if v is None:
            continue
        if out and out[-1][2] == v and out[-1][1] == a:
            out[-1][1] = e
        else:
            out.append([a, e, v])
    return [tuple(x) for x in out]


def _annotate(t: Transcription, lid: str, text: str, spans, language: str | None) -> None:
    """A line's formatting, edits, statuses and languages (by the file's annotator, 0)."""
    fmts = []
    for a, e, fmt in _grouped(spans, lambda r: r.fmt or None):
        a, e = _trim(text, a, e)
        if e > a:
            f = {k: True for k in ("italic", "bold", "underline", "strikethrough") if k in fmt}
            script = "super" if "super" in fmt else "sub" if "sub" in fmt else "baseline"
            if f or script != "baseline":
                fmts.append(Formatting(charspan=[a, e], script=script, **f))
    if fmts:
        t.line(lid).reading.formatting = fmts
    for a, e, (kind, other, _) in _grouped(spans, lambda r: r.edit):
        a, e = _trim(text, a, e)
        if e > a:
            t.edits.append(Edit(annotator=0, target=f"{lid}[{a}:{e}]", kind=kind, text=other))
    for a, e, (status, _) in _grouped(spans, lambda r: r.status):
        if status == "gap":
            t.classify(0, f"{lid}[{a}:{a}]", "status", "gap")
            continue
        a, e = _trim(text, a, e)
        if e > a:
            t.classify(0, f"{lid}[{a}:{e}]", "status", status)
    for a, e, value in _grouped(spans, lambda r: r.language):
        a, e = _trim(text, a, e)
        if e > a and value != language:
            t.classify(0, f"{lid}[{a}:{e}]", "language", value)


def _build(blocks: list[_Block], source: Source, ground_truth: bool, language: str | None) -> Transcription:
    """The blocks as the transcription's regions and lines (``linecaster.formats._xml.transcription``): furniture
    above the page's text first, then the body (each block's notes and captions after it), then the furniture below;
    then the lines' formatting, edits, statuses, languages and divided words, and the notes', captions' and
    descriptions' links."""
    seq: list[tuple[_Block, tuple[str, _Block] | None]] = []
    for part in ("header", "body", "footer"):
        for b in blocks:
            if b.part == part:
                seq.append((b, None))
                seq += [(n, ("note_of", b)) for n in b.notes] + [(c, ("caption_of", b)) for c in b.captions]
    used = {x.id for b, _ in seq for x in (b, *(i for i in b.items if isinstance(i, _Break))) if x.id}
    counter: Counter = Counter()

    def new_id(base: str, own: str | None = None) -> str:
        """``own`` (an ``xml:id``) where it is free, else ``base`` numbered (``paragraph_0``, ``paragraph_0_l0``)."""
        if own and own not in taken:
            taken.add(own)
            return own
        while True:
            counter[base] += 1
            candidate = f"{base}{counter[base] - 1}"
            if candidate not in used and candidate not in taken:
                taken.add(candidate)
                return candidate

    taken: set[str] = set()
    page = {"language": language_tag(language)}
    regions, lines, extra, rids, links, descriptions = [], [], [], {}, [], []
    for b, link in seq:
        found = _lines(b.items)
        rid, holds = None, page
        if b.role is not None:
            polygon, box = b.polygon, b.box
            if polygon is None and box is None:
                boxed = [brk.box for brk, _, _ in found if brk.box is not None]
                box = X.bounds([p for bx in boxed for p in X.rect(bx)]) if boxed else None
            if not found and box is None and b.role not in TEXTLESS:
                continue
            rid = new_id(f"{b.role}_", b.id)
            fr = X.FileRegion(rid, b.role, b.raw, polygon, box, heading_level=b.heading_level,
                              reading_order=len(regions))
            holds = X.narrower(fr, {"language": b.language}, page)
            regions.append(fr)
            rids[id(b)] = rid
            if link is not None and id(link[1]) in rids:
                links.append((link[0], rid, rids[id(link[1])]))
            if b.description:
                descriptions.append((rid, b.description))
        for j, (brk, text, spans) in enumerate(found):
            lid = new_id(f"{rid}_l" if rid else "line_", brk.id)
            fl = X.FileLine(lid, rid, len(lines), j if rid else 0, brk.box, brk.polygon, brk.baseline, text=text)
            lh = X.narrower(fl, {"language": brk.language}, holds)
            lines.append(fl)
            extra.append((lid, rid, text, spans, lh["language"], brk.joins))
    t = X.transcription(regions, lines, [], source, ground_truth, language=page["language"])
    for lid, _, text, spans, lang, _ in extra:
        _annotate(t, lid, text, spans, lang)
    for k, (lid, rid, text, _, _, joins) in enumerate(extra):
        if not joins or k == 0:
            continue
        prev = next((x for x in reversed(extra[:k]) if x[1] == rid), None) if rid else None
        prev = prev or extra[k - 1]
        first, second = re.search(r"\S+$", prev[2]), re.match(r"\S+", text)
        if first and second:
            whole = first.group().rstrip(DIVISION_MARKS) + second.group()
            t.edits.append(Edit(annotator=0, target=f"{prev[0]}[{first.start()}:{first.end()}]", kind="joined",
                                text=whole))
            t.edits.append(Edit(annotator=0, target=f"{lid}[{second.start()}:{second.end()}]", kind="joined",
                                text=whole))
    for kind, source_id, target_id in links:
        t.links.append(Link(annotator=0, kind=kind, source=source_id, target=target_id))
    for rid, text in descriptions:
        t.descriptions.append(Description(annotator=0, target=rid, kind="description", text=text))
    return t


def from_tei(data: bytes | str, *, page: int | str = 1, uri: str | None = None,
             ground_truth: bool = False) -> Transcription:
    """Reads one page of a TEI P5 document (the subset this module's docstring lists) into a transcription.

    The document's first form decides: a ``sourceDoc`` with surfaces (diplomatic, with geometry), else its ``text``
    (with geometry from its ``facsimile`` where its elements point to zones, else without). The page's surface gives
    ``source.image_width``/``image_height`` (its ``graphic``'s size, else its own extent) and coordinates are
    pixels of that image. The file is the transcription's one annotator (kind ``file``; ``human`` with
    ``ground_truth``), named ``tei``; regions are classified by their content role.

    Args:
        data: the TEI file's content.
        page: the page to read: its number (1-based) among the surfaces of a ``sourceDoc`` or the pages of the text
            (``pb`` begins one), or the ``xml:id`` of its ``surface`` or ``pb``; default the first. A page the
            document does not have is a ``ValueError``.
        uri: the transcription's ``source.uri``; default the URL of the page's ``graphic``.
        ground_truth: the file is a ground truth: ``source.kind`` ``ground_truth``, and its annotator is people
            (kind ``human``).

    Example:
        from linecaster.formats.tei import from_tei

        with open("edition.xml", "rb") as f:
            t = from_tei(f.read(), page=2)
        print([t.role(r.id) for r in t.regions], t.edits[:3])
    """
    root, ns = X.parse_xml(data)
    tei = root if root.tag == "TEI" else next(root.iter("TEI"), root)
    namespace = {"tei__namespace": ns} if ns else {}
    source_doc = X.child(tei, "sourceDoc")
    surfaces = _surfaces(source_doc) if source_doc is not None else []
    width = height = graphic = None
    if surfaces:
        surface = surfaces[_page_index(surfaces, page, lambda s: {s.get("id")})]
        grid, width, height, graphic = _surface(surface)
        groups = [a for a in surface.iterancestors() if a.tag == "surfaceGrp"][::-1]
        ctx = _context(tei, source_doc, *groups, surface)
        blocks = _diplomatic(surface, grid, ctx)
    else:
        text = X.child(tei, "text")
        if text is None and tei.tag == "text":
            text = tei
        ids = {el.get("id"): el for f in tei.iter("facsimile") for el in f.iter() if el.get("id")}
        grids: dict = {}

        def grid_of(el) -> _Grid:
            s = _surface_of(el)
            if id(s) not in grids:
                grids[id(s)] = _surface(s)[0] if s is not None else _Grid()
            return grids[id(s)]

        def facs(el):
            ref = next((r[1:] for r in (el.get("facs") or "").split() if r.startswith("#")), None)
            return ids.get(ref) if ref else None

        def geometry(el):
            z = facs(el)
            if z is None or z.tag != "zone":
                return None
            return _coords(z, grid_of(z))

        if text is None:
            blocks, ctx = [], _context(tei)
            surface = None
        else:
            pbs = list(text.iter("pb"))
            lead = _lead(text, pbs[0]) if pbs else True
            pages = ([None] if lead else []) + pbs

            def names(pb) -> set:
                if pb is None:
                    return set()
                s = _surface_of(facs(pb))
                return {pb.get("id"), s.get("id") if s is not None else None} - {None}

            target = _page_index(pages, page, names)
            ctx = _context(tei, text, X.child(text, "body"))
            w = _Walk(geometry, target=target, start=0 if lead else -1)
            try:
                w.element(text, _context(tei))
            except _Done:
                pass
            w.flush()
            blocks = w.blocks
            pb = pages[target]
            surface = _surface_of(facs(pb)) if pb is not None else None
            every = [s for f in tei.iter("facsimile") for s in X.children(f, "surface")]
            if surface is None and target < len(every):        # no pb[@facs]: the surface of the page's number
                surface = every[target]
        if surface is not None:
            _, width, height, graphic = _surface(surface)
    source = Source(kind="converted", format="tei", uri=uri or graphic, image_width=width, image_height=height,
                    **namespace)
    return _build(blocks, source, ground_truth, ctx["language"])
