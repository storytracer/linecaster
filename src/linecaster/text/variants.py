"""Texts from transcriptions, in linecaster's era-neutral vocabulary: three independent dimensions,
each transform moving one step on one of them.

* **character fidelity**: *as written* (NFC only: ſ, ligatures, r rotunda, superscript e kept) or
  *normalized* (``normalize``: the explicit mapping table below, then NFC; never NFKC, spelling
  never modernized);
* **flow**: *as laid out* (one line per printed line, pages separated by a form feed) or *flowed*
  (``join_lines``: lines of a region joined into a paragraph with line-end hyphens resolved;
  paragraphs joined across page breaks where they continue);
* **scope**: *full page* or *body only* (``FURNITURE`` regions, running heads and page numbers, and
  pictures left out).

The named variants are points on these dimensions:

========================  ==================  ==========  =========  ==============
variant                   fidelity            flow        scope      format
========================  ==================  ==========  =========  ==============
``verbatim_txt``          as written          as laid out full page  text/plain
``readable_txt``          normalised          flowed      body only  text/plain
``readable_md``           normalised          flowed      body only  text/markdown
========================  ==================  ==========  =========  ==============

Normalization table: ſ -> s; the typographic ligatures ﬀ ﬁ ﬂ ﬃ ﬄ ﬅ ﬆ -> their letters; r rotunda
ꝛ/Ꝛ -> r/R; a combining superscript e (U+0364) over a, o, u (A, O, U) -> ä, ö, ü (Ä, Ö, Ü); over any
other letter it stays. æ, œ, ø, å, ß and every other character stay (NFKC would also flatten
superscripts, fractions and typographic characters).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ..data.transcription import Transcription, render_table

NORMALIZE_MAP = str.maketrans({
    "ſ": "s",                                   # ſ long s
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    "ﬅ": "st",                                  # ﬅ long s + t
    "ﬆ": "st",                                  # ﬆ
    "ꝛ": "r", "Ꝛ": "R",                    # ꝛ Ꝛ r rotunda
})
_SUPERSCRIPT_E = re.compile("([aouAOU])ͤ")
_UMLAUT = {"a": "ä", "o": "ö", "u": "ü", "A": "Ä", "O": "Ö", "U": "Ü"}
#: line-end hyphens: hyphen-minus, not sign (Fraktur), double oblique hyphen, hyphen, double hyphen
HYPHENS = ("-", "¬", "⸗", "‐", "=")
SENTENCE_END = (".", "!", "?", ":", ";", "“", "”", "»", "«", '"', ")")
FURNITURE = frozenset({"page_header", "page_footer"})
NO_TEXT = frozenset({"picture", "chart"})
#: variant -> (fidelity, flow, scope, format)
VARIANTS = {
    "verbatim_txt": ("as written", "as laid out", "full page", "text/plain"),
    "readable_txt": ("normalised", "flowed", "body only", "text/plain"),
    "readable_md": ("normalised", "flowed", "body only", "text/markdown"),
}


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def normalize(s: str) -> str:
    """Character fidelity *as written* -> *normalized* (the table in the module docstring), NFC."""
    s = nfc(s)
    s = _SUPERSCRIPT_E.sub(lambda m: _UMLAUT[m.group(1)], s)
    return nfc(s.translate(NORMALIZE_MAP))


def join_lines(a: str, b: str) -> str:
    """Flow two pieces of text across a line break: a line-end hyphen before a lower-case letter is
    removed (``Entwicklungs-``/``geschichte``), before anything else kept as ``-`` (``Nord-``/
    ``Amerika``); otherwise the pieces are joined with a space."""
    if not a:
        return b
    if not b:
        return a
    if a.endswith(HYPHENS) and len(a) > 1 and not a[-2].isspace():
        return a[:-1] + b if b[0].islower() else a[:-1] + "-" + b
    return a + " " + b


@dataclass
class Block:
    """A flowed region: ``kind`` is title, heading, list_item, paragraph or table (``table`` holds the
    region's table structure from a tables step; it is rendered, never flowed)."""

    kind: str
    label: str
    text: str
    level: int | None = None
    table: dict | None = None


def table_plain(table: dict) -> str:
    """A table structure as plain text: one line per row, cells separated by a tab (spans ignored:
    a cell stands at its first row and column)."""
    cells = table.get("cells") or []
    n_rows = max((c["row"] + 1 for c in cells), default=0)
    n_cols = max((c["col"] + 1 for c in cells), default=0)
    grid = [[""] * n_cols for _ in range(n_rows)]
    for c in cells:
        grid[c["row"]][c["col"]] = " ".join(c["text"].split())
    return "\n".join("\t".join(row).rstrip("\t") for row in grid)


def _map_table(table: dict, f) -> dict:
    return {**table, "cells": [{**c, "text": f(c["text"])} for c in table.get("cells") or []]}


def page_blocks(t: Transcription, skip_labels: frozenset[str] = FURNITURE | NO_TEXT) -> list[Block]:
    """The page's regions in reading order (regions without an order last), each region's recognized
    lines flowed into one block (NFC first, whatever the producer delivered); a region with a table
    structure (``region.extra["table"]``) becomes a ``table`` block; regions labeled in
    ``skip_labels`` are left out (body only). Lines without a known region form one paragraph at the
    end."""
    order = {r.id: (r.reading_order is None, r.reading_order or 0, i) for i, r in enumerate(t.regions)}
    regions = {r.id: r for r in t.regions}
    by_region: dict[str | None, list] = {}
    for ln in sorted(t.lines, key=lambda ln: ln.reading_order):
        if ln.text is None or not ln.text.strip():
            continue
        by_region.setdefault(ln.region_id if ln.region_id in regions else None, []).append(ln)
    keys: list[str | None] = sorted((k for k in by_region if k is not None), key=lambda k: order[k])
    if None in by_region:
        keys.append(None)
    blocks = []
    for k in keys:
        r = regions.get(k) if k is not None else None
        label = r.label if r is not None else "text"
        if label in skip_labels:
            continue
        table = (r.extra.get("table") or {}) if r is not None else {}
        if table.get("cells"):
            blocks.append(Block("table", label, "", table=_map_table(table, nfc)))
            continue
        text = ""
        for ln in by_region[k]:
            text = join_lines(text, nfc(ln.text.strip()))
        kind = {"title": "title", "section_header": "heading", "list_item": "list_item"}.get(label, "paragraph")
        blocks.append(Block(kind, label, text, r.heading_level if r is not None else None))
    return blocks


def continues(prev: Block, nxt: Block) -> bool:
    """Whether a text paragraph at the foot of a page continues in the first one of the next page:
    it ends in a hyphen or without sentence-final punctuation (the case of the next word is no
    signal: German nouns are capitalized)."""
    if prev.kind != "paragraph" or nxt.kind != "paragraph" or prev.label != "text" or nxt.label != "text":
        return False
    if prev.text.endswith(HYPHENS):
        return True
    return bool(nxt.text) and not prev.text.rstrip().endswith(SENTENCE_END)


def book_blocks(pages: list[Transcription], skip_labels: frozenset[str] = FURNITURE | NO_TEXT) -> list[Block]:
    """The blocks of consecutive pages, paragraphs joined across page breaks where they continue. Only
    a page's final block may continue (a footnote or caption after the text blocks a join)."""
    out: list[Block] = []
    for t in pages:
        blocks = page_blocks(t, skip_labels)
        if out and blocks and continues(out[-1], blocks[0]):
            out[-1] = Block("paragraph", "text", join_lines(out[-1].text, blocks[0].text))
            blocks = blocks[1:]
        out.extend(blocks)
    return out


_MD_START = re.compile(r"^([#>*+\-]|\d+[.)])(\s|$)")


def render(blocks: list[Block], markdown: bool = False, normalized: bool = True) -> str:
    """Blocks -> text, paragraphs separated by a blank line. Markdown: ``#`` title, ``##`` section header
    (``#`` x (heading_level + 1) when the layout gives a level), ``- `` list item, tables as Markdown
    pipe tables (HTML when a cell spans); a paragraph that would read as Markdown syntax is escaped.
    Plain text: tables one row per line, cells separated by tabs."""
    parts = []
    for b in blocks:
        if b.kind == "table":
            table = _map_table(b.table, normalize if normalized else nfc)
            parts.append(render_table(table) if markdown else table_plain(table))
            continue
        text = normalize(b.text) if normalized else nfc(b.text)
        if not markdown:
            parts.append(text)
        elif b.kind == "title":
            parts.append("# " + text)
        elif b.kind == "heading":
            parts.append("#" * min(6, (b.level or 1) + 1) + " " + text)
        elif b.kind == "list_item":
            parts.append("- " + text)
        else:
            parts.append("\\" + text if _MD_START.match(text) else text)
    return nfc("\n\n".join(p for p in parts if p))


def verbatim(pages: list[Transcription]) -> str:
    """As written, as laid out, full page: each page's text (``Transcription.text``: lines in reading
    order, tables as Markdown/HTML tables), pages joined with a form feed (split on ``\\f`` to get the
    pages back; an empty page stays an empty string); NFC."""
    return "\f".join(nfc(t.text) for t in pages)


def variants(pages: list[Transcription]) -> dict[str, str]:
    """The three named variants of consecutive pages (a book)."""
    blocks = book_blocks(pages)
    return {"verbatim_txt": verbatim(pages), "readable_txt": render(blocks), "readable_md": render(blocks, markdown=True)}
