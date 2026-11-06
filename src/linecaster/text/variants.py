"""Texts from transcriptions, in linecaster's era-neutral vocabulary: three independent dimensions,
each transform moving one step on one of them.

* **character fidelity**: *as written* (NFC only: ſ, ligatures, r rotunda, superscript e kept) or
  *normalized* (``normalize``: the explicit mapping table below, then NFC; never NFKC, spelling
  never modernized);
* **flow**: *as laid out* (one line per printed line, pages separated by a form feed) or *flowed* (the
  recomposition's paragraphs, ``Transcription.paragraphs``: rows joined, division marks removed, paragraphs
  continued across regions and page breaks where the recomposition of the item continued them);
* **scope**: *full page* or *body only* (``FURNITURE`` regions, running heads and page numbers, and
  pictures left out).

The readable variants are made from an item recomposed as one (``Recomposer(unit="item")``) and normalized
(``CharacterNormalizer``: ``Paragraph.normalized`` and the table cells'); ``normalize`` is the mapping table the
``normalization.latin-historic.v1`` engine applies.

The named variants are points on these dimensions:

========================  ==================  ==========  =========  ==============
variant                   fidelity            flow        scope      format
========================  ==================  ==========  =========  ==============
``verbatim_txt``          as written          as laid out full page  text/plain
``readable_txt``          normalized          flowed      body only  text/plain
``readable_md``           normalized          flowed      body only  text/markdown
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
FURNITURE = frozenset({"page_header", "page_footer"})
NO_TEXT = frozenset({"picture", "chart"})
#: variant -> (fidelity, flow, scope, format)
VARIANTS = {
    "verbatim_txt": ("as written", "as laid out", "full page", "text/plain"),
    "readable_txt": ("normalized", "flowed", "body only", "text/plain"),
    "readable_md": ("normalized", "flowed", "body only", "text/markdown"),
}


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def normalize(s: str) -> str:
    """Character fidelity *as written* -> *normalized* (the table in the module docstring), NFC."""
    s = nfc(s)
    s = _SUPERSCRIPT_E.sub(lambda m: _UMLAUT[m.group(1)], s)
    return nfc(s.translate(NORMALIZE_MAP))


@dataclass
class Block:
    """A flowed piece of an item's body: ``kind`` is title, heading, list_item, paragraph or table (``table``
    holds the region's table structure from a tables step; it is rendered, never flowed); ``text`` as written,
    ``normalized`` its normalized text (``None``: not normalized)."""

    kind: str
    label: str
    text: str
    normalized: str | None = None
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


def _table(table: dict, normalized: bool) -> dict:
    """A table structure with each cell's text NFC, or its normalized text (``CharacterNormalizer``; as written
    where a cell has none)."""
    def text(c):
        return nfc(c["normalized"] if normalized and c.get("normalized") is not None else c.get("text") or "")
    return {**table, "cells": [{**c, "text": text(c)} for c in table.get("cells") or []]}


#: region label -> block kind (every other text label is a paragraph)
KINDS = {"title": "title", "section_header": "heading", "list_item": "list_item"}


def body_blocks(pages: list[Transcription], page_ids: list[str] | None = None,
                skip_labels: frozenset[str] = FURNITURE | NO_TEXT) -> list[Block]:
    """The body of consecutive pages (an item) from their recomposition: each page's regions in reading order
    (regions without an order last), each paragraph a block (``Transcription.paragraphs``; a paragraph that
    continues another, in an earlier region or on an earlier page, is appended to that one's block with the
    continuation's separator), a region with a table structure a ``table`` block, a formula region's LaTeX a
    paragraph; regions labeled in ``skip_labels`` are left out (body only). ``page_ids`` name the pages as the
    recomposition named them (``ParagraphRef.page_id``; default ``#1``, ``#2``, ...). A page without paragraphs
    contributes only its tables and formulas."""
    ids = list(page_ids) if page_ids is not None else [f"#{k + 1}" for k in range(len(pages))]
    out: list[Block] = []
    open_: dict[tuple[str, str], tuple[Block, str]] = {}     # (page id, paragraph id) -> the block it goes on in
    for key, t in zip(ids, pages):
        paragraphs: dict[str | None, list] = {}
        for p in t.paragraphs:
            paragraphs.setdefault(p.region_id, []).append(p)
        regions = sorted(t.regions, key=lambda r: r.reading_order if r.reading_order is not None else 1 << 30)
        units = [(r.id, r.label, r) for r in regions]
        if None in paragraphs and not t.regions:          # a text-only page: its paragraphs without a region
            units = [(None, "text", None)]
        for rid, label, r in units:
            if label in skip_labels:
                continue
            extra = r.extra if r is not None else {}
            if (extra.get("table") or {}).get("cells"):
                out.append(Block("table", label, "", table=extra["table"]))
                continue
            if extra.get("formula"):
                out.append(Block("paragraph", label, nfc(extra["formula"]), nfc(extra["formula"])))
                continue
            own = paragraphs.get(rid, [])
            standalone = len(own) == 1 and not any(ch.isalpha() for ch in own[0].text)      # a page number
            for p in own:
                text, normalized = nfc(p.text), None if p.normalized is None else nfc(p.normalized)
                continued = None if standalone or p.continues_from is None else open_.pop((key, p.id), None)
                if continued is not None:
                    b, sep = continued
                    b.text += sep + text
                    if b.normalized is not None and normalized is not None:
                        b.normalized += sep + normalized
                    else:
                        b.normalized = None
                else:
                    b = Block(KINDS.get(label, "paragraph"), label, text, normalized,
                              r.heading_level if r is not None else None)
                    out.append(b)
                if p.continues is not None:
                    sep = next((d.separator for d in reversed(p.decisions) if d.kind == "continuation"), None) or ""
                    open_[(p.continues.page_id or key, p.continues.id)] = (b, sep)
    return out


_MD_START = re.compile(r"^([#>*+\-]|\d+[.)])(\s|$)")


def render(blocks: list[Block], markdown: bool = False, normalized: bool = True) -> str:
    """Blocks -> text, paragraphs separated by a blank line: their normalized text (as written where a block has
    none), or as written with ``normalized=False``. Markdown: ``#`` title, ``##`` section header (``#`` x
    (heading_level + 1) when the layout gives a level), ``- `` list item, tables as Markdown pipe tables (HTML when
    a cell spans); a paragraph that would read as Markdown syntax is escaped. Plain text: tables one row per line,
    cells separated by tabs. NFC."""
    parts = []
    for b in blocks:
        if b.kind == "table":
            table = _table(b.table, normalized)
            parts.append(render_table(table) if markdown else table_plain(table))
            continue
        text = nfc(b.normalized if normalized and b.normalized is not None else b.text)
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


def variants(pages: list[Transcription], page_ids: list[str] | None = None) -> dict[str, str]:
    """The three named variants of consecutive pages (an item): ``verbatim_txt`` from the lines as laid out, the
    readable ones from the recomposition's paragraphs, normalized (``body_blocks``; ``page_ids`` as there)."""
    blocks = body_blocks(pages, page_ids)
    return {"verbatim_txt": verbatim(pages), "readable_txt": render(blocks), "readable_md": render(blocks, markdown=True)}
