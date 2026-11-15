"""An item's Page: pages read together: what runs on from one page onto the next.

ProofreadPage transcribes a scanned book page by page; a paragraph that runs on onto the next page is two pieces, and
the wiki joins them when it transcludes the pages into a main-namespace page, unless the page ends the paragraph
(``{{nop}}``, or a block at the page's end: the importer's measurement ``ends_paragraph``) or the next page begins
with a block (a centred heading, a table: ``starts_paragraph``). ``link_pages`` records the joins as the data model's
links between the pages' regions (``<page_id>#<region>``): the last body paragraph of a page that runs on
``runs_into`` the next page's first body paragraph, which ``continues`` it; a page's first continued footnote
(``footnote_continued``: Cite's ``<ref follow=...>``) ``continues`` the last footnote of the page before; a table that
runs on (``table_runs_on``) ``runs_into`` the next page's first table where that one continues it (``table_continues``),
and where the next page goes on in the middle of a cell (``cell``) its last cell into the next's first. linecaster's
item texts (``linecaster.text.variants``) and documents flow them into one.

A word divided across a page break (``{{hws}}``/``{{hwe}}``: each half a ``joined`` edit of its span, the whole word
its text) is written as the wiki writes it in the main namespace: ``join_divided_words`` pairs the halves and gives
each line a ``joined`` edit of the whole line, the first half left out and the second written as the whole word
(the document builder writes a line's ``joined`` edit as its text). A compound divided at its own hyphen keeps it.
"""
from __future__ import annotations

import unicodedata

from linecaster.data import Link, Transcription
from linecaster.data.refs import cell as cell_ref, parse
from linecaster.data.transcription import Edit

BODY = ("paragraph",)
NOTES = ("footnote", "footnote_continued")


def _importer(t: Transcription) -> int:
    return next(i for i, a in enumerate(t.annotators) if a.kind == "rule" and a.step == "import")


def _ordered(t: Transcription, roles: tuple[str, ...]) -> list[str]:
    order = t.order()
    return [r for r in (order.regions if order else []) if t.role(r) in roles and not t.region(r).parent]


def link_pages(pages: list[tuple[str, Transcription]]) -> int:
    """Links the consecutive pages of one item, given in order as ``(page_id, transcription)``; returns how many
    joins it recorded. A page's own annotator of step ``import`` makes the links (its ``ends_paragraph``, the next
    page's ``starts_paragraph``). Divided words are joined too (``join_divided_words``)."""
    join_divided_words(pages)
    joins = 0
    for (pid, t), (nid, n) in zip(pages, pages[1:]):
        a = _importer(t)
        ends = t.annotators[a].measurements.get("ends_paragraph", True) or \
            n.annotators[_importer(n)].measurements.get("starts_paragraph", False)
        body, following = _ordered(t, BODY + ("heading", "title", "table")), _ordered(n, BODY + ("heading", "title",
                                                                                                "table"))
        if not ends and body and following and t.role(body[-1]) == "paragraph" and n.role(following[0]) == "paragraph":
            t.links.append(Link(annotator=a, kind="runs_into", source=body[-1], target=f"{nid}#{following[0]}"))
            n.links.append(Link(annotator=_importer(n), kind="continues", source=following[0],
                                target=f"{pid}#{body[-1]}"))
            joins += 1
        m, mn = t.annotators[a].measurements, n.annotators[_importer(n)].measurements
        if body and following and t.role(body[-1]) == "table" and n.role(following[0]) == "table" \
                and m.get("table_runs_on") and mn.get("table_continues") in ("rows", "cell"):
            last, first = body[-1], following[0]
            t.links.append(Link(annotator=a, kind="runs_into", source=last, target=f"{nid}#{first}"))
            n.links.append(Link(annotator=_importer(n), kind="continues", source=first, target=f"{pid}#{last}"))
            prev, nxt = t.table(last), n.table(first)
            if mn["table_continues"] == "cell" and prev is not None and nxt is not None and prev.cells and nxt.cells:
                end = max(prev.cells, key=lambda c: (c.start_row, c.start_col))
                top = min(c.start_row for c in nxt.cells)          # the cell in the last cell's column, else the first
                start = min((c for c in nxt.cells if c.start_row == top),
                            key=lambda c: (c.start_col != end.start_col, c.start_col))
                a_ref, b_ref = cell_ref(last, end.start_row, end.start_col), cell_ref(first, start.start_row,
                                                                                       start.start_col)
                t.links.append(Link(annotator=a, kind="runs_into", source=a_ref, target=f"{nid}#{b_ref}"))
                n.links.append(Link(annotator=_importer(n), kind="continues", source=b_ref, target=f"{pid}#{a_ref}"))
            joins += 1
        notes = _ordered(t, NOTES)
        first = next((r for r in _ordered(n, NOTES) if n.role(r) == "footnote_continued"), None)
        if notes and first is not None:
            n.links.append(Link(annotator=_importer(n), kind="continues", source=first, target=f"{pid}#{notes[-1]}"))
            t.links.append(Link(annotator=a, kind="runs_into", source=notes[-1], target=f"{nid}#{first}"))
            joins += 1
    return joins


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)                     # a ligature as printed ("\ufb02ush": "flushed")


def _first_half(half: str, whole: str) -> bool:
    return bool(half.strip()) and _nfkc(whole).startswith(_nfkc(half).rstrip().rstrip("-\u00ad\u2010").rstrip())


def _last_half(half: str, whole: str) -> bool:
    return bool(half.strip()) and _nfkc(whole).endswith(_nfkc(half).strip())


def join_divided_words(pages: list[tuple[str, Transcription]]) -> int:
    """Pairs the halves of each word divided across a page break, given the item's pages in order: a ``joined`` edit
    of a span of a line (the half as printed, the whole word its text) whose span begins the whole word, and the next
    one with the same word whose span ends it, on a later page or later on the same page (the halves compared in
    Unicode's compatibility form: a ligature as printed). Each line with a half gets a ``joined`` edit of the
    whole line (by the page's importer): the first half left out (with the space before it at the line's end), the
    second written as the whole word, as the wiki writes them in the main namespace. Returns the words joined; a half
    without its other half stays as printed."""
    open_: dict[str, tuple[int, str, tuple[int, int]]] = {}         # whole word -> its first half: page, line, span
    cuts: dict[tuple[int, str], list[tuple[int, int, str]]] = {}
    words = 0
    for i, (_, t) in enumerate(pages):
        order = {lid: k for k, lid in enumerate(t.order().lines)} if t.order() else {}
        halves = []
        for e in t.edits:
            if e.kind != "joined":
                continue
            ref = parse(e.target)
            if ref.span is None or ref.page is not None:
                continue
            ln = t.line(ref.id)
            if ln is None or ln.reading is None:
                continue
            halves.append((order.get(ln.id, len(order)), ref.span, ln.id, ln.reading.text[ref.span[0]:ref.span[1]],
                           e.text))
        for _, span, lid, half, whole in sorted(halves):
            first = open_.get(whole)
            if first is not None and (first[0], first[1], first[2]) != (i, lid, span) and _last_half(half, whole):
                cuts.setdefault(first[:2], []).append((*first[2], ""))
                cuts.setdefault((i, lid), []).append((*span, whole))
                del open_[whole]
                words += 1
            elif _first_half(half, whole):
                open_[whole] = (i, lid, span)
    for (i, lid), parts in cuts.items():
        t = pages[i][1]
        text = t.line(lid).reading.text
        for a, e, new in sorted(parts, reverse=True):
            if not new and not text[e:].strip():
                text = text[:a].rstrip()
            else:
                text = text[:a] + new + text[e:]
        t.edits.append(Edit(annotator=_importer(t), target=lid, kind="joined", text=text))
    return words
