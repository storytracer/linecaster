"""Texts from transcriptions, in linecaster's era-neutral vocabulary: three independent dimensions,
each transform moving one step on one of them.

* **character fidelity**: *as written* (NFC only: ſ, ligatures, r rotunda, superscript e kept) or
  *normalized* (``normalize``: the explicit mapping table below, then NFC; never NFKC, spelling
  never modernized);
* **flow**: *as laid out* (one line per printed line, pages separated by a form feed) or *flowed* (the
  recomposition's paragraphs, ``Transcription.paragraphs``: rows joined, division marks removed, paragraphs
  continued across regions and page breaks where the recomposition of the item continued them);
* **scope**: *full page* (the rendering policy's ``body`` and ``furniture`` layers) or *body only* (its ``body``
  layer: running heads and page numbers left out, and the text read inside pictures and charts).

Regions the policy puts in no layer (``none``: removed, suppressed, duplicate) are left out of every variant. The
readable variants are made from an item recomposed as one (``Recomposer(unit="item")``) and normalized
(``CharacterNormalizer``: ``normalized`` edits of the paragraphs and the table cells), each text with the edits the
policy names for the variant (``RenderingPolicy.edits``: the latest of them per text, else the text as written);
``normalize`` is the mapping table the ``normalization.latin-historic.v1`` engine applies.

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

from ..data.policy import DEFAULT_POLICY, RenderingPolicy
from ..data.refs import cell as cell_ref
from ..data.transcription import Cell, Table, Transcription, render_table
from .recomposition import continuation, paragraphs as paragraphs_of, split_ref

NORMALIZE_MAP = str.maketrans({
    "ſ": "s",                                   # ſ long s
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    "ﬅ": "st",                                  # ﬅ long s + t
    "ﬆ": "st",                                  # ﬆ
    "ꝛ": "r", "Ꝛ": "R",                    # ꝛ Ꝛ r rotunda
})
_SUPERSCRIPT_E = re.compile("([aouAOU])ͤ")
_UMLAUT = {"a": "ä", "o": "ö", "u": "ü", "A": "Ä", "O": "Ö", "U": "Ü"}
#: the Docling labels whose text is left out of the flowed variants: the text read inside a picture or chart
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
    holds the region's table structure from a tables step, ``cells`` each cell's text with the variant's edits, by
    ``Cell.ref``; a table is rendered, never flowed); ``text`` as written, ``normalized`` its text with the
    variant's edits (``None``: the text as written)."""

    kind: str
    label: str
    text: str
    normalized: str | None = None
    level: int | None = None
    table: Table | None = None
    cells: dict[str, str] | None = None


def table_plain(table: Table, text=lambda c: c.text) -> str:
    """A table structure as plain text: one line per row, cells separated by a tab (spans ignored:
    a cell stands at its first row and column). ``text(cell)`` gives a cell's text (its own by default)."""
    cells = table.cells
    n_rows = max((c.start_row + 1 for c in cells), default=0)
    n_cols = max((c.start_col + 1 for c in cells), default=0)
    grid = [[""] * n_cols for _ in range(n_rows)]
    for c in cells:
        grid[c.start_row][c.start_col] = " ".join(text(c).split())
    return "\n".join("\t".join(row).rstrip("\t") for row in grid)


def _cell_text(b: Block, normalized: bool):
    """A table block's cell text: NFC, with the variant's edits (``normalized``) or as written."""
    def text(c: Cell) -> str:
        edited = b.cells.get(c.ref) if normalized and b.cells else None
        return nfc(edited if edited is not None else c.text or "")
    return text


#: region label -> block kind (every other text label is a paragraph)
KINDS = {"title": "title", "section_header": "heading", "list_item": "list_item"}


def body_blocks(pages: list[Transcription], page_ids: list[str] | None = None, policy: RenderingPolicy = DEFAULT_POLICY,
                variant: str = "readable_txt") -> list[Block]:
    """The body of consecutive pages (an item) from their recomposition: each page's regions in reading order
    (regions without an order last), each paragraph a block (the latest recomposition's paragraphs; a paragraph that
    continues another, in an earlier region or on an earlier page, is appended to that one's block with the
    continuation's separator), a region with a table structure a ``table`` block, a formula region's LaTeX a
    paragraph; only regions ``policy`` puts in the ``body`` layer, and no text read inside a picture or chart
    (``NO_TEXT``). Texts carry ``variant``'s edits (``policy.edits``). ``page_ids`` name the pages as the
    recomposition named them (``<page id>#<id>``; default ``#1``, ``#2``, ...). A page without paragraphs
    contributes only its tables and formulas."""
    ids = list(page_ids) if page_ids is not None else [f"#{k + 1}" for k in range(len(pages))]
    kinds = policy.kinds(variant)
    out: list[Block] = []
    open_: dict[tuple[str, str], tuple[Block, str]] = {}     # (page id, paragraph id) -> the block it goes on in
    for key, t in zip(ids, pages):
        paragraphs: dict[str | None, list] = {}
        for p in paragraphs_of(t):
            paragraphs.setdefault(p.region, []).append(p)
        units = [(r.id, t.label(r.id)) for r in t.ordered_regions() if policy.layer_of(t, r.id) == "body"]
        if None in paragraphs and not t.regions:          # a text-only page: its paragraphs without a region
            units = [(None, "text")]
        for rid, label in units:
            if label in NO_TEXT:
                continue
            table = t.table(rid) if rid is not None else None
            if table is not None and table.cells:
                cells = {c.ref: e for c in table.cells if (e := t.edit(cell_ref(rid, c.start_row, c.start_col), kinds))
                         is not None}
                out.append(Block("table", label, "", table=table, cells=cells))
                continue
            formula = t.formula(rid) if rid is not None else None
            if formula is not None and formula.latex:
                out.append(Block("paragraph", label, nfc(formula.latex), nfc(formula.latex)))
                continue
            own = paragraphs.get(rid, [])
            standalone = len(own) == 1 and not any(ch.isalpha() for ch in own[0].text)      # a page number
            for p in own:
                edited = t.edit(p.id, kinds)
                text, normalized = nfc(p.text), nfc(edited if edited is not None else p.text)
                continued = (None if standalone or continuation(t, p, "continues") is None
                             else open_.pop((key, p.id), None))
                if continued is not None:
                    b, sep = continued
                    b.text += sep + text
                    b.normalized += sep + normalized
                else:
                    b = Block(KINDS.get(label, "paragraph"), label, text, normalized,
                              t.heading_level(rid) if rid is not None else None)
                    out.append(b)
                runs_into = continuation(t, p, "runs_into")
                if runs_into is not None:
                    sep = next((d.separator for d in reversed(p.decisions) if d.kind == "continuation"), None) or ""
                    page, pid = split_ref(runs_into)
                    open_[(page or key, pid)] = (b, sep)
    return out


_MD_START = re.compile(r"^([#>*+\-]|\d+[.)])(\s|$)")


def render(blocks: list[Block], markdown: bool = False, normalized: bool = True) -> str:
    """Blocks -> text, paragraphs separated by a blank line: their texts with the variant's edits (as written where a
    block has none), or as written with ``normalized=False``. Markdown: ``#`` title, ``##`` section header (``#`` x
    (heading_level + 1) when the layout gives a level), ``- `` list item, tables as Markdown pipe tables (HTML when
    a cell spans); a paragraph that would read as Markdown syntax is escaped. Plain text: tables one row per line,
    cells separated by tabs. NFC."""
    parts = []
    for b in blocks:
        if b.kind == "table":
            text = _cell_text(b, normalized)
            parts.append(render_table(b.table, text) if markdown else table_plain(b.table, text))
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
    order with their ``nfc`` edits, tables as Markdown/HTML tables, regions the default policy puts nowhere left
    out), pages joined with a form feed (split on ``\\f`` to get the pages back; an empty page stays an empty
    string); NFC."""
    return "\f".join(nfc(t.text) for t in pages)


def variants(pages: list[Transcription], page_ids: list[str] | None = None) -> dict[str, str]:
    """The three named variants of consecutive pages (an item) under the default policy: ``verbatim_txt`` from the
    lines as laid out, the readable ones from the recomposition's paragraphs, normalized (``body_blocks``;
    ``page_ids`` as there)."""
    txt = body_blocks(pages, page_ids, variant="readable_txt")
    same = DEFAULT_POLICY.kinds("readable_md") == DEFAULT_POLICY.kinds("readable_txt")
    md = txt if same else body_blocks(pages, page_ids, variant="readable_md")
    return {"verbatim_txt": verbatim(pages), "readable_txt": render(txt), "readable_md": render(md, markdown=True)}
