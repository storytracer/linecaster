"""Transcription strategies on documents: ``apply(document, strategy)`` writes a strategy's document from the literal
one the builder makes (``linecaster.document.builder``).

A strategy is ``literal`` (the document as it is) or an ordered list of normalizations (``linecaster.catalog``:
``Catalog.strategy``), each applied to every block in turn:

- a character rule (``linecaster.normalization.rules``) to a block's text and a table's cells (a formula block's LaTeX
  stays as it is);
- ``edits``: the source's edits of those kinds (a block's edit spans: corrections, expansions, regularizations)
  written in place of the characters they read;
- ``divided_words``: a word divided across lines or pages where the source marks it (``joined`` edit spans: each half
  as printed, the whole word its text), the halves paired in reading order (a first half begins the whole word, the
  next half with the same word ends it, on a later block or later in the same one): the first half left out (with
  the space before it at its row's end), the whole word where the second stands, a compound's own hyphen kept;
- ``division_marks``: the division marks no source marked, resolved by a named method at each wrap: ``unicode-marks``
  (squiddleocr's rule, ``linecaster.text.paragraphs.resolve_mark``, the document's words as its lexicon): a mark
  it removes is gone and the rows joined;
- ``flow``: every wrap (``Block.wraps``: a break of the layout's) joined, by a space unless Unicode's line breaking
  joins the two words (``separator``); a row that still ends with a division mark is joined without a space, the
  mark kept (``de-pends``): nothing is guessed. Every other row break (a verse line) stays.

Spans, wraps and origins move with the text they cover (``linecaster.text.offsets.moved``); a span on removed text
goes. The result names its strategy (``Document.strategy``).
"""
from __future__ import annotations

import unicodedata

from linecaster.normalization.rules import apply_rule
from linecaster.text.offsets import moved
from linecaster.document.model import Block, Document

#: the block kinds whose text is not words (a formula's LaTeX)
NOT_TEXT = frozenset({"formula"})


def apply(doc: Document, strategy) -> Document:
    """``doc`` written by ``strategy`` (a ``ResolvedStrategy``, or its name: ``literal``, a strategy's id,
    normalizations joined by ``+``); ``doc`` itself is left as it is."""
    from linecaster.catalog.registry import catalog
    from linecaster.catalog.schema import TEXT_RULES

    if isinstance(strategy, str):
        strategy = catalog().strategy(strategy, use="output")
    out = doc.model_copy(deep=True)
    out.strategy = strategy.id
    for n in strategy.normalizations:
        kind = next(iter(n.rule))
        value = n.rule[kind]
        if kind in TEXT_RULES:
            for b in out.blocks:
                if b.kind not in NOT_TEXT and b.text:
                    _rewrite(b, apply_rule(b.text, n.rule))
                if b.grid is not None:
                    for c in b.grid.cells:
                        new = apply_rule(c.text, n.rule)
                        if new != c.text:
                            mv = moved(c.text, new)
                            c.formulas = [list(x) for x in (mv(a, e) for a, e in c.formulas) if x[1] > x[0]]
                            c.text = new
        elif kind == "edits":
            for b in out.blocks:
                _apply_edits(b, set(value))
        elif kind == "divided_words":
            _divided_words(out)
        elif kind == "division_marks":
            _division_marks(out, value)
        elif kind == "flow":
            for b in out.blocks:
                _flow(b)
    return out


def _rewrite(b: Block, new: str, mv=None, kept=None) -> None:
    """``b``'s text made ``new``: its spans, wraps and origins moved with it (by ``mv``, a span mover; default the
    one ``linecaster.text.offsets.moved`` infers from the two texts; ``kept``: whether a wrap's newline is still
    there, default: the character it moves to is one)."""
    if new == b.text:
        return
    mv = mv or moved(b.text, new)
    spans = []
    for s in b.spans:
        a, e = mv(s.start, s.end)
        if e > a or (s.edit is not None and e >= a and s.start == s.end):
            spans.append(s.model_copy(update={"start": a, "end": e}))
    b.spans = spans
    b.wraps = sorted({w2 for w in b.wraps if (kept is None or kept(w)) and (w2 := mv(w, w + 1)[0]) < len(new)
                      and new[w2] == "\n"})
    for o in b.origins:
        if o.span:
            o.span = list(mv(o.span[0], o.span[1]))
    b.text = new


def _replace(b: Block, parts: list[tuple[int, int, str]], drop_edits: set[int] = frozenset()) -> None:
    """``b``'s characters ``[a, e)`` replaced by each part's text (parts not overlapping); the spans at the indices
    ``drop_edits`` (applied edits) go. Positions move by the parts themselves (``_part_mover``), not by a diff."""
    parts = sorted(parts)
    text = b.text
    for a, e, new in reversed(parts):
        text = text[:a] + new + text[e:]
    if drop_edits:
        b.spans = [s for k, s in enumerate(b.spans) if k not in drop_edits]
    _rewrite(b, text, _part_mover(parts, b.text), lambda w: not any(a <= w < e for a, e, _ in parts))


def _part_mover(parts: list[tuple[int, int, str]], old: str):
    """A span mover through ``parts`` (sorted, not overlapping) of the text ``old``: a position before a part stays,
    after it moves by the part's change of length, inside it by the part's own change (``moved`` on the part's old
    and new text: what both share stays under its span); a span ending where a part begins does not take it in; an
    insertion where a span begins comes before it."""
    def at(pos: int, end: bool) -> int:
        shift = 0
        for a, e, new in parts:
            if (a < e <= pos) or (a == e < pos) or (a == e == pos and not end):   # the part lies before pos
                shift += len(new) - (e - a)
            elif a < pos < e:                            # inside the part
                inner = moved(old[a:e], new)(pos - a, pos - a)
                return a + shift + (inner[1] if end else inner[0])
            else:
                break
        return pos + shift

    return lambda a, e: (at(a, False), at(e, True))


def _apply_edits(b: Block, kinds: set[str]) -> None:
    hits = [(k, s) for k, s in enumerate(b.spans) if s.edit in kinds and s.edit_text is not None]
    if hits:
        _replace(b, [(s.start, s.end, s.edit_text) for _, s in hits], {k for k, _ in hits})


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


#: the marks a divided word's first half may end with (ALTO's ``HYP``: hyphens, the soft hyphen, ¬, ⸗ and =)
DIVISION_MARKS = "-\u00ad\u2010¬⸗="


def _first_half(half: str, whole: str) -> bool:
    return bool(half.strip()) and _nfkc(whole).startswith(_nfkc(half).rstrip().rstrip(DIVISION_MARKS).rstrip())


def _last_half(half: str, whole: str) -> bool:
    return bool(half.strip()) and _nfkc(whole).endswith(_nfkc(half).strip())


def _page_of(b: Block, pos: int) -> int:
    """The page a character of ``b`` comes from: the origin whose span holds it (the first origin's page without
    one; 0 without origins)."""
    for o in b.origins:
        if o.span and o.span[0] <= pos < max(o.span[1], o.span[0] + 1):
            return o.page or 0
    return (b.origins[0].page or 0) if b.origins else 0


def _divided_words(doc: Document) -> None:
    """The halves of each source-marked divided word paired in the order of the pages they stand on (then of the
    blocks, then within a block), written as the whole word. Page order, not block order: a first half in a page's
    furniture (a running foot) comes after the paragraph that continues onto the next page in the document's blocks,
    but before the second half on the page."""
    open_: dict[str, tuple[int, int]] = {}                   # whole word -> its first half: block, span index
    parts: dict[int, list[tuple[int, int, str]]] = {}
    applied: dict[int, set[int]] = {}
    halves = sorted((_page_of(b, s.start), bi, s.start, si) for bi, b in enumerate(doc.blocks)
                    for si, s in enumerate(b.spans) if s.edit == "joined" and s.edit_text)
    for _, bi, _, si in halves:
        b = doc.blocks[bi]
        s = b.spans[si]
        half, whole = b.text[s.start:s.end], s.edit_text
        first = open_.get(whole)
        if first is not None and first != (bi, si) and _last_half(half, whole):
            fb, fs = first
            fspan = doc.blocks[fb].spans[fs]
            ftext = doc.blocks[fb].text
            a, row_end = fspan.start, ftext.find("\n", fspan.end)
            rest = ftext[fspan.end:row_end if row_end >= 0 else len(ftext)]
            if not rest.strip():                         # the half ends its row: the space before it goes too
                while a > 0 and ftext[a - 1] in " \t":
                    a -= 1
            parts.setdefault(fb, []).append((a, fspan.end, ""))
            applied.setdefault(fb, set()).add(fs)
            parts.setdefault(bi, []).append((s.start, s.end, whole))
            applied.setdefault(bi, set()).add(si)
            del open_[whole]
        elif _first_half(half, whole):
            open_[whole] = (bi, si)
    for bi, ps in parts.items():
        _replace(doc.blocks[bi], ps, applied.get(bi, set()))


def _rows_at(text: str, w: int) -> tuple[str, str]:
    """The rows before and after the break at offset ``w``."""
    start = text.rfind("\n", 0, w) + 1
    end = text.find("\n", w + 1)
    return text[start:w], text[w + 1:end if end >= 0 else len(text)]


def _division_marks(doc: Document, method: str) -> None:
    from linecaster.text.paragraphs import Lexicon, ends_with_mark, resolve_mark

    if method != "unicode-marks":
        raise ValueError(f"unknown division-mark method {method!r}")
    lexicon = Lexicon()
    for b in doc.blocks:
        if b.kind not in NOT_TEXT and b.text:
            lexicon.add(b.text)
    for b in doc.blocks:
        for w in sorted(b.wraps, reverse=True):
            prev, nxt = _rows_at(b.text, w)
            if ends_with_mark(prev) and resolve_mark(prev, nxt, lexicon)[0]:
                mark = w - (len(prev) - len(prev.rstrip())) - 1          # the mark, before any space at the row end
                _replace(b, [(mark, w + 1, "")])


def _flow(b: Block) -> None:
    from linecaster.text.paragraphs import ends_with_mark, separator

    if not b.wraps:
        return
    parts = []
    for w in b.wraps:
        prev, nxt = _rows_at(b.text, w)
        sep = "" if ends_with_mark(prev) else separator(prev, nxt)
        parts.append((w, w + 1, sep))
    b.wraps = []
    _replace(b, parts)
