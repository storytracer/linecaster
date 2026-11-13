"""Recomposition: running text from the visual rows of a region (the reading transcription).

The engine ``recomposition.unicode.v1`` (``linecaster.engines.recomposition``) runs it, the ``Composer`` builds
documents and ``linecaster.text.variants`` the readable item texts from what it makes. Every threshold below is a field of
``Thresholds`` (today's values its defaults), the engine's options.

Typesetting turned the text into lines: it broke it at line ends, sometimes inside a word with a
division mark, justified it, indented paragraph starts and continued it across columns and pages.
The line-level exports keep that diplomatic form. This module inverts it for the document exports:
rows of a region are joined into paragraphs, division marks that the typesetter added are removed,
and a paragraph that runs on into the next region is continued there. Every decision is made from
Unicode character properties and geometry, never from a language name, plus the document's own
words as evidence for the one ambiguous case (a hyphen that may belong to the word).

Decisions at a row end, in order:

- **Paragraph boundary** (``break_reason``): the row starts indented from the region's start
  margin by about an em (``indent``, 0.8 em), or the gap above it exceeds the modal leading clearly
  (``gap_leading`` 0.6 of it and ``gap_height`` 0.5 of the taller row), or in justified text the previous row
  stopped short of the end margin (``short_row`` 1.5 em and ``short_row_width`` a quarter of the frame). A region
  is justified when at least ``justified_rows`` (3) rows have and ``justified_share`` (0.6) of them reach the end
  margin within ``end_margin`` (0.6 em). Start and end margins follow the writing direction (``rtl``).
- **Division mark** (``resolve_mark``): a hyphen by Unicode's Line_Break property (HY, or a BA/HH
  character whose name says HYPHEN: hyphen, soft hyphen, the Fraktur ``⸗``, ``⹀``, the Armenian
  hyphen; the maqaf is not named so and dashes are other classes) or a convention mark, after a
  letter at the row end, is the typesetter's and removed, unless the next row starts with an
  uppercase letter or a digit (a compound split at its own hyphen) or the document attests the
  hyphenated form and not the joined one. After a Hebrew letter a mark divides a word only when the
  next row is Hebrew script too (UAX #14 LB21a: Hebrew does not divide words; Yiddish print does).
- **Separator** (``separator``): nothing when UAX #14 permits a line break between the two
  boundary words without a space (ideographs, Thai, after full-width punctuation), else a space.
- **Region continuation** (``continues``): a text region whose last row ends without sentence-final
  punctuation, at the end margin or with a division mark, continues into the next text region in
  reading order when that region's first row is not indented and starts with a letter (a capital
  too, German capitalizes every noun, except after a division mark).

Each decision is recorded on the paragraph it concerns (``linecaster.data.Decision``: a mark removed, a hyphen
kept, a paragraph break, with its reason). Rows without geometry (a text-only transcription) are recomposed by the
character rules alone: no paragraph breaks, a region is one paragraph, and only a division mark leaves it open.

On a ``Transcription`` (``region_rows``, ``paragraphs``, ``continuation``): a region's rows are its lines on each
visual row (``Transcription.rows``), their texts as written (the ``nfc`` and ``joined`` edits applied); the
paragraphs of a page are those of its latest recomposition (a later one makes them anew), and a paragraph's
continuation is a link by the same annotator: ``runs_into`` the paragraph it runs on into, ``continues`` the one it
continues, each a reference ``<id>`` on the same page or ``<page id>#<id>`` on another (``ref``, ``split_ref``).

Out of scope, by design: glyph normalization (long s, ligatures), spelling modernization, emphasis
from letter-spacing, Korean's unmarked in-word breaks, vertical writing.
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Sequence

from uniseg.linebreak import LB, line_break, line_break_boundaries
from uniseg.sentencebreak import SB, sentence_break
from uniseg.wordbreak import words

from ..data.geometry import BBox
from ..data.transcription import Decision, Line, Transcription
from ..data.transcription import Paragraph as ParagraphRange
from .typography import AS_WRITTEN, line_bbox, union

#: Marks by convention, unknown to Unicode as hyphens: the not sign, which some transcription
#: conventions (and kraken models trained on them) write for a line-end hyphen.
CONVENTION_MARKS = "¬"


@dataclass(frozen=True)
class Thresholds:
    """The geometric thresholds of the recomposition, in ems (the region's median row height) unless said
    otherwise, and the convention marks; the defaults are the ``unicode-recomposition`` preset's values."""

    indent: float = 0.8              # a row indented this far starts a paragraph; a region's first row, no continuation
    gap_leading: float = 0.6         # a gap above a row larger than this share of the leading ...
    gap_height: float = 0.5          # ... and than this share of the taller row's height is a blank line
    short_row: float = 1.5           # in justified text a row ending this short of the end margin ...
    short_row_width: float = 0.25    # ... and this share of the frame's width closes the paragraph
    end_margin: float = 0.6          # a row ending this close to the end margin reaches it
    justified_rows: int = 3          # a region of at least this many rows ...
    justified_share: float = 0.6     # ... of which this share reach the end margin is justified
    marks: str = CONVENTION_MARKS    # characters a transcription convention writes for a line-end hyphen


DEFAULT_THRESHOLDS = Thresholds()


def is_letter(ch: str) -> bool:
    return unicodedata.category(ch).startswith("L")


def is_mark(ch: str, marks: str = CONVENTION_MARKS) -> bool:
    """A character the typesetter may put at a line end when dividing a word (``marks``: the convention marks)."""
    if ch and ch in marks:
        return True
    lb = line_break(ch)
    return lb == LB.HY or (lb.name in ("BA", "HH", "GL") and "HYPHEN" in unicodedata.name(ch, ""))


def _hebrew(ch: str) -> bool:
    return line_break(ch) == LB.HL


def word_tokens(text: str, marks: str = CONVENTION_MARKS) -> list[str]:
    """UAX #29 words that contain a letter, hyphenated compounds kept together (``EU-Staaten``)."""
    out: list[str] = []
    for w in words(text):
        if out and is_mark(w[-1:], marks) and len(w) == 1 and out[-1] and is_letter(out[-1][-1]):
            out[-1] += w                                    # a hyphen right after a word
            continue
        if out and is_mark(out[-1][-1:], marks) and len(out[-1]) > 1 and any(is_letter(c) for c in w):
            out[-1] += w                                    # the word after that hyphen
            continue
        if any(is_letter(c) for c in w):
            out.append(w)
    return [t for t in (_strip_marks(w, marks) for w in out) if t]


def _strip_marks(w: str, marks: str = CONVENTION_MARKS) -> str:
    while w and is_mark(w[-1], marks):
        w = w[:-1]
    return w


@dataclass
class Row:
    """One visual row of a region: its text (boxes on the row already joined) and its bounds (``None``: a
    text-only transcription, no geometry)."""

    text: str
    bbox: BBox | None
    index: int = 0        # position in the region's rows


def region_rows(t: Transcription, lines: list[Line], kinds: tuple[str, ...] = AS_WRITTEN) -> list[Row]:
    """A region's visual rows: the texts of its ``lines`` on each row (``Transcription.rows``, in the order given)
    joined with a space, with ``kinds`` edits applied, the row's box the union of their boxes, in row order."""
    rows = t.rows()
    grouped: dict[int, list[Line]] = {}
    for ln in lines:
        grouped.setdefault(rows.get(ln.id, 0), []).append(ln)
    out = []
    for i, k in enumerate(sorted(grouped)):
        b = union([line_bbox(ln) for ln in grouped[k]])
        out.append(Row(" ".join(x for ln in grouped[k] if (x := t.text_of(ln, kinds))), b, i))
    return out


def row_lines(t: Transcription, lines: list[Line]) -> list[list[str]]:
    """The ids of ``lines`` on each visual row, in row order (``region_rows``' rows)."""
    rows = t.rows()
    grouped: dict[int, list[str]] = {}
    for ln in lines:
        grouped.setdefault(rows.get(ln.id, 0), []).append(ln.id)
    return [grouped[k] for k in sorted(grouped)]


def paragraphs(t: Transcription) -> list[ParagraphRange]:
    """The paragraphs of the page's latest recomposition (the latest annotator that made any)."""
    found = t.paragraphs
    if not found:
        return []
    latest = max(p.annotator for p in found)
    return [p for p in found if p.annotator == latest]


def continuation(t: Transcription, p: ParagraphRange, kind: str) -> str | None:
    """The reference a paragraph's ``kind`` link (``runs_into``, ``continues``) by its own annotator names."""
    return next((ln.target for ln in reversed(t.links)
                 if ln.source == p.id and ln.kind == kind and ln.annotator == p.annotator), None)


def ref(page_id: str | None, range_id: str) -> str:
    """The reference to a range piece: ``<id>`` on the same page (``page_id`` ``None``), else ``<page id>#<id>``."""
    return range_id if page_id is None else f"{page_id}#{range_id}"


def split_ref(value: str) -> tuple[str | None, str]:
    """(page id or ``None``, id) of a reference to a range piece (``ref``)."""
    page, _, rid = value.rpartition("#")
    return page or None, rid


@dataclass
class Span:
    row: int              # row index in the region
    start: int            # character span in the paragraph text
    end: int


@dataclass
class Paragraph:
    text: str
    spans: list[Span] = field(default_factory=list)
    bbox: BBox | None = None
    open_end: bool = False       # may continue into the next region
    decisions: list[Decision] = field(default_factory=list)   # at its rows (``Decision.row``: index into spans)


@dataclass
class Stats:
    marks_removed: int = 0
    marks_kept: int = 0
    paragraphs: int = 0
    continuations: int = 0
    examples: list[str] = field(default_factory=list)     # kept marks and continuations, for SQUIDDLE_VERBOSE

    def note(self, kind: str, before: str, after: str) -> None:
        if len(self.examples) < 200:
            self.examples.append(f"{kind}: …{before[-30:]} | {after[:30]}…")

    def __iadd__(self, other: "Stats") -> "Stats":
        self.marks_removed += other.marks_removed
        self.marks_kept += other.marks_kept
        self.paragraphs += other.paragraphs
        self.continuations += other.continuations
        self.examples = (self.examples + other.examples)[:200]
        return self

    def describe(self) -> str:
        return (f"{self.paragraphs} paragraphs, {self.continuations} continued across regions, "
                f"division marks removed {self.marks_removed}, kept {self.marks_kept}")


class Lexicon:
    """Word counts over everything recognized so far in a run: the document as its own dictionary."""

    def __init__(self, marks: str = CONVENTION_MARKS):
        self.counts: Counter[str] = Counter()
        self.marks = marks

    def add(self, text: str) -> None:
        for line in text.splitlines():      # line by line: a line-end hyphen must not attest a compound
            self.counts.update(w.casefold() for w in word_tokens(line, self.marks))

    def attests(self, word: str) -> int:
        return self.counts.get(word.casefold(), 0)


# ------------------------------------------------------------------------------------------ geometry
@dataclass
class Margins:
    """The region's writing frame from its rows: start and end margins, em, leading, justification."""

    start: float          # x of the start margin (left for LTR, right for RTL)
    end: float
    em: float             # median row height
    leading: float        # median distance between consecutive row tops
    justified: bool

    @classmethod
    def of(cls, rows: Sequence[Row], rtl: bool = False, th: Thresholds = DEFAULT_THRESHOLDS) -> "Margins":
        heights = sorted(r.bbox.height for r in rows)
        em = heights[len(heights) // 2] if heights else 1.0
        starts = sorted((r.bbox.x1 if rtl else r.bbox.x0) for r in rows)
        ends = sorted((r.bbox.x0 if rtl else r.bbox.x1) for r in rows)
        # the start margin is the outermost start (rows are indented inwards, never outwards)
        start = starts[-1] if rtl else starts[0]
        end = ends[0] if rtl else ends[-1]
        tops = sorted(r.bbox.y0 for r in rows)
        gaps = sorted(b - a for a, b in zip(tops, tops[1:]) if b > a)
        leading = gaps[len(gaps) // 2] if gaps else em
        reaching = sum(1 for r in rows if abs((r.bbox.x0 if rtl else r.bbox.x1) - end) <= th.end_margin * em)
        return cls(start, end, max(em, 1.0), max(leading, 1.0),
                   justified=len(rows) >= th.justified_rows and reaching >= th.justified_share * len(rows))

    def indent(self, row: Row, rtl: bool) -> float:
        return (self.start - row.bbox.x1) if rtl else (row.bbox.x0 - self.start)

    def shortfall(self, row: Row, rtl: bool) -> float:
        return (row.bbox.x0 - self.end) if rtl else (self.end - row.bbox.x1)


def break_reason(prev: Row, row: Row, m: Margins, rtl: bool = False, th: Thresholds = DEFAULT_THRESHOLDS) -> str | None:
    """Why ``row`` starts a new paragraph after ``prev`` (``indent``, ``gap``, ``short_row``), or None."""
    if m.indent(row, rtl) >= th.indent * m.em and m.indent(prev, rtl) < th.indent * m.em:
        return "indent"
    gap = row.bbox.y0 - prev.bbox.y1                    # blank space between the rows
    if gap > th.gap_leading * m.leading and gap > th.gap_height * max(prev.bbox.height, row.bbox.height):
        return "gap"                                    # about a blank line
    if (m.justified and m.shortfall(prev, rtl) > th.short_row * m.em and m.indent(row, rtl) < th.indent * m.em
            and m.shortfall(prev, rtl) > th.short_row_width * (m.end - m.start if not rtl else m.start - m.end)):
        return "short_row"
    return None


def paragraph_break(prev: Row, row: Row, m: Margins, rtl: bool = False, th: Thresholds = DEFAULT_THRESHOLDS) -> bool:
    """Does ``row`` start a new paragraph after ``prev``?"""
    return break_reason(prev, row, m, rtl, th) is not None


# ---------------------------------------------------------------------------------------- characters
def _last_char(text: str) -> str:
    t = text.rstrip()
    return t[-1] if t else ""


def _first_char(text: str) -> str:
    t = text.lstrip()
    return t[0] if t else ""


def ends_with_mark(text: str, marks: str = CONVENTION_MARKS) -> bool:
    t = text.rstrip()
    return len(t) >= 2 and is_mark(t[-1], marks) and is_letter(t[-2])


def resolve_mark(prev_text: str, next_text: str, lexicon: Lexicon | None = None,
                 marks: str = CONVENTION_MARKS) -> tuple[bool, str]:
    """For a row ending in a division mark: (removed?, the attested hyphenated form or "").

    Removed unless the next row starts with an uppercase letter or a digit, the mark follows a
    Hebrew letter and the next row is not Hebrew script, or the lexicon attests the hyphenated
    form and not the joined form."""
    nxt = _first_char(next_text)
    if not nxt or not (is_letter(nxt) or nxt.isdigit()):
        return False, ""
    if nxt.isupper() or nxt.isdigit():
        return False, ""
    stripped = prev_text.rstrip()
    if _hebrew(stripped[-2]) and not _hebrew(nxt):
        return False, ""
    a = word_tokens(stripped[:-1], marks)
    b = word_tokens(next_text, marks)
    if lexicon is not None and a and b:
        head, tail = a[-1], b[0]
        joined, hyphenated = head + tail, f"{head}-{tail}"
        if lexicon.attests(hyphenated) and not lexicon.attests(joined):
            return False, hyphenated
    return True, ""


def kept_reason(prev_text: str, next_text: str, hyphenated: str = "") -> str:
    """Why ``resolve_mark`` kept the hyphen at the end of ``prev_text`` (``Decision`` reasons of ``hyphen_kept``):
    the next row starts with no letter, a capital, a digit, it is in another script, or the document attests the
    hyphenated form."""
    if hyphenated:
        return "attested"
    nxt = _first_char(next_text)
    if not nxt or not (is_letter(nxt) or nxt.isdigit()):
        return "no_letter_follows"
    if nxt.isdigit():
        return "digit_follows"
    if nxt.isupper():
        return "capital_follows"
    return "script_change"


def separator(prev_text: str, next_text: str) -> str:
    """"" when UAX #14 allows a line break right at the junction of the boundary words, else a space."""
    a = prev_text.rstrip().split()[-1:] or [""]
    b = next_text.lstrip().split()[:1] or [""]
    a, b = a[0], b[0]
    if not a or not b:
        return " "
    if line_break(a[-1]) == LB.SA and line_break(b[0]) == LB.SA:
        return ""      # Thai, Lao, Khmer, Myanmar: UAX #14 leaves breaks inside runs to a dictionary; no spaces in any case
    return "" if len(a) in set(line_break_boundaries(a + b)) else " "


def sentence_open(text: str) -> bool:
    """The row does not end a sentence: no sentence-terminal punctuation (closing quotes and brackets
    may follow it), by Unicode's Sentence_Break property."""
    t = text.rstrip()
    while t and sentence_break(t[-1]) == SB.CLOSE:
        t = t[:-1].rstrip()
    return bool(t) and sentence_break(t[-1]) not in (SB.STERM, SB.ATERM)


def continues(prev: Paragraph, first_row: Row, m: Margins | None, rtl: bool = False,
              th: Thresholds = DEFAULT_THRESHOLDS) -> bool:
    """Whether the last paragraph of a region runs on into a region whose first row is ``first_row`` (``m``: that
    region's margins; ``None`` without geometry, then no indent can refuse it)."""
    if not prev.open_end:
        return False
    if m is not None and m.indent(first_row, rtl) >= th.indent * m.em:
        return False
    ch = _first_char(first_row.text)
    if not ch or not is_letter(ch):
        return False
    # after a division mark a capital would make a compound; across regions that is more often a wrong
    # pairing of regions than a compound, so it is refused. Without a mark a capital is allowed: German
    # capitalizes every noun.
    return not (ch.isupper() and ends_with_mark(prev.text, th.marks))


class Rules:
    """The decisions at a row end that depend on the characters around it: ``resolve_mark``, ``kept_reason`` and
    ``separator``, this module's Unicode rules. ``reflow_rows`` takes another object with the same methods
    (``kept_reason`` optional), e.g. an engine that routes each decision to a strategy by script
    (``linecaster.engines.recomposition``)."""

    resolve_mark = staticmethod(resolve_mark)
    kept_reason = staticmethod(kept_reason)
    separator = staticmethod(separator)


UNICODE_RULES = Rules()


# ---------------------------------------------------------------------------------------------- rows
def mark_decision(rules, prev_text: str, next_text: str, lexicon: Lexicon | None,
                  row: int) -> tuple[bool, str, Decision]:
    """``rules``' decision on the division mark that ends ``prev_text`` before ``next_text``: (removed?, the attested
    hyphenated form or "", the ``Decision`` at ``row``)."""
    removed, hyphenated = rules.resolve_mark(prev_text, next_text, lexicon)
    if removed:
        return True, "", Decision(kind="mark_removed", reason="letter_follows", row=row)
    reason = getattr(rules, "kept_reason", kept_reason)(prev_text, next_text, hyphenated)
    return False, hyphenated, Decision(kind="hyphen_kept", reason=reason, row=row)


def reflow_rows(rows: Sequence[Row], rtl: bool = False, lexicon: Lexicon | None = None, single: bool = False,
                stats: Stats | None = None, rules=UNICODE_RULES,
                th: Thresholds = DEFAULT_THRESHOLDS) -> list[Paragraph]:
    """Join the rows of one region into paragraphs, each with its decisions. ``single`` (headings) makes one
    paragraph. ``rules`` makes the decisions that depend on characters (``Rules``). Rows without boxes (a
    text-only transcription) make one paragraph, left open only by a division mark."""
    stats = stats if stats is not None else Stats()
    rows = [r for r in rows if r.text.strip()]
    if not rows:
        return []
    geometric = all(r.bbox is not None for r in rows)
    single = single or not geometric
    m = Margins.of(rows, rtl, th) if geometric else None
    paragraphs: list[Paragraph] = []
    current: Paragraph | None = None
    for i, row in enumerate(rows):
        text = row.text.strip()
        reason = None if current is None or single else break_reason(rows[i - 1], row, m, rtl, th)
        if current is None or reason is not None:
            if current is not None:
                _close(current, rows)
            current = Paragraph(text, [Span(row.index, 0, len(text))])
            if reason is not None:
                current.decisions.append(Decision(kind="paragraph_break", reason=reason, row=0))
            paragraphs.append(current)
            continue
        prev_text = current.text
        if ends_with_mark(prev_text, th.marks):
            removed, hyphenated, decision = mark_decision(rules, prev_text, text, lexicon, len(current.spans) - 1)
            current.decisions.append(decision)
            if removed:
                current.text = prev_text[:-1]
                current.spans[-1].end -= 1
                sep = ""
                stats.marks_removed += 1
            else:
                sep = "" if hyphenated or is_mark(prev_text[-1], th.marks) else " "
                stats.marks_kept += 1
                stats.note("kept", prev_text, text)
        else:
            sep = rules.separator(prev_text, text)
        start = len(current.text) + len(sep)
        current.text = current.text + sep + text
        current.spans.append(Span(row.index, start, len(current.text)))
    _close(current, rows)
    last, last_row = paragraphs[-1], rows[-1]
    # a single row is its own margin, so only a division mark can leave it open
    reaches = m is not None and len(rows) >= 2 and m.shortfall(last_row, rtl) <= th.end_margin * m.em
    last.open_end = ((not single or not geometric) and sentence_open(last.text)
                     and (ends_with_mark(last.text, th.marks) or reaches))
    stats.paragraphs += len(paragraphs)
    return paragraphs


def _close(p: Paragraph, rows: Sequence[Row]) -> None:
    by_index = {r.index: r for r in rows}
    boxes = [by_index[s.row].bbox for s in p.spans if s.row in by_index and by_index[s.row].bbox is not None]
    if boxes:
        p.bbox = BBox(min(b.x0 for b in boxes), min(b.y0 for b in boxes), max(b.x1 for b in boxes), max(b.y1 for b in boxes))


def join(prev: Paragraph, nxt: Paragraph, lexicon: Lexicon | None = None, stats: Stats | None = None,
         rules=UNICODE_RULES, th: Thresholds = DEFAULT_THRESHOLDS) -> tuple[str, str, Decision | None]:
    """Continuing ``prev`` (its text: everything it holds so far) with ``nxt``: the joined text, what joins them
    (``""`` or a space, after the division mark is removed or kept) and the decision on that mark (``None``:
    ``prev`` ends without one). A kept mark is followed by a space unless the document attests the hyphenated
    form."""
    stats = stats if stats is not None else Stats()
    if ends_with_mark(prev.text, th.marks):
        removed, hyphenated, decision = mark_decision(rules, prev.text, nxt.text, lexicon, 0)
        if removed:
            stats.marks_removed += 1
            return prev.text[:-1] + nxt.text, "", decision
        stats.marks_kept += 1
        stats.note("kept", prev.text, nxt.text)
        sep = "" if hyphenated else " "
        return prev.text + sep + nxt.text, sep, decision
    stats.note("continued", prev.text, nxt.text)
    sep = rules.separator(prev.text, nxt.text)
    return prev.text + sep + nxt.text, sep, None
