"""The recomposition engine and the composition against the legacy builder (``legacy_builder``, the DocumentBuilder
as it recomposed while it built, on the page/2 shape of each page: ``legacy_docling.page2``; a DoclingDocument, so
this needs the ``docling`` extra): the same content, block by block (kind, text, layer, section, and each origin's
page, region, box and characters), per page and per item, from lines and from paragraphs, with and without sections,
on the fixtures and on random pages (headings, page numbers, pictures, tables, formulas, indents, gaps, short rows,
division marks of every kind)."""
from __future__ import annotations

import random

import pytest

pytest.importorskip("docling_core")

from conftest import page_t, page_to_compose, sample_transcription  # noqa: E402
from legacy_builder import LegacyDocumentBuilder  # noqa: E402
from legacy_docling import page2  # noqa: E402
from linecaster.data import Transcription  # noqa: E402
from linecaster.data.upgrade import upgrade_transcription  # noqa: E402
from linecaster.document.strategy import apply  # noqa: E402
from linecaster.engines import LinkedDocumentEngine, UnicodeParagraphsEngine  # noqa: E402
from linecaster.engines.paragraphs.rules import paragraphs, split_ref  # noqa: E402

#: the legacy builder's Docling labels -> the document's block kinds
KIND = {"text": "paragraph", "section_header": "heading", "document_index": "toc_entry"}

#: docling-core warns about list items outside a list group (both builders add them so)
pytestmark = pytest.mark.filterwarnings("ignore:ListItem parent must be a list group:DeprecationWarning")

WORDS = ("der", "Nord", "See", "und", "the", "nest", "is", "built", "of", "dead", "grasses", "Ab", "lagerungen", "1914",
         "Kanton", "Bern", "zu", "sammen", "ſchön", "Fluß", "élan", "naïve", "co", "operation", "12", "Ostsee", "Raum",
         "(vgl.", "–")
ENDS = ("", "", "", ".", ",", ";", "-", "-", "-", "¬", "⸗", "‐", ".", "!", "?", ":")


def _box(x, y, w, h):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def random_page(rng: random.Random, n: int) -> Transcription:
    regions, lines, y, order = [], [], 60.0, 0
    for k in range(rng.randint(1, 7)):
        kind = rng.choice(["text"] * 6 + ["title", "section_header", "number", "picture", "table", "formula",
                                          "caption", "footnote", "page_header", "list_item", "empty"])
        rid = f"r{n}_{k}"
        label = {"number": "page_footer", "empty": "text"}.get(kind, kind)
        extra = {}
        if kind == "table":
            extra["table"] = {"num_rows": 1, "num_cols": 1, "cells": [{"text": "a", "row": 0, "col": 0}]}
        if kind == "formula":
            extra["formula"] = "x^2"
        rows = 0 if kind == "empty" else 1 if kind in ("title", "section_header", "number") else rng.randint(1, 8)
        top = y
        for r in range(rows):
            if kind == "number":
                text = rng.choice(["12", "13", "p. 4", "iv"])
            else:
                words = rng.choices(WORDS, k=rng.randint(1, 7))
                if rng.random() < 0.3:
                    words[0] = words[0].capitalize()
                text = " ".join(words) + rng.choice(ENDS)
            if rng.random() < 0.05:
                text = ""
            y += rng.choice([30, 30, 30, 30, 55])                     # sometimes a blank line
            indent = rng.choice([0, 0, 0, 0, 40, 5])
            short = rng.choice([0, 0, 0, 0, 0, 300, 20])
            pieces = 2 if rng.random() < 0.15 else 1                  # two lines on one row
            x0, x1 = 100 + indent, 900 - short
            if pieces == 2 and len(text.split()) > 1:
                cut = text.split()
                half = len(cut) // 2
                mid = (x0 + x1) / 2
                lines.append(dict(id=f"{rid}_l{r}a", region_id=rid, row=r, polygon=_box(x0, y, mid - 5 - x0, 20),
                                  bbox=[x0, y, mid - 5 - x0, 20], text=" ".join(cut[:half])))
                lines.append(dict(id=f"{rid}_l{r}b", region_id=rid, row=r, polygon=_box(mid + 5, y, x1 - mid - 5, 20),
                                  bbox=[mid + 5, y, x1 - mid - 5, 20], text=" ".join(cut[half:])))
            else:
                lines.append(dict(id=f"{rid}_l{r}", region_id=rid, row=r, polygon=_box(x0, y, x1 - x0, 20),
                                  bbox=[x0, y, x1 - x0, 20], text=text))
        y += 40
        no_order = rng.random() < 0.05
        level = rng.choice([None, 1, 2, 3]) if kind in ("title", "section_header") else None
        regions.append(dict(id=rid, label=label, raw_label="number" if kind == "number" else label,
                            polygon=_box(90, top, 820, y - top), bbox=[90, top, 820, y - top],
                            reading_order=None if no_order else order, extra=extra, heading_level=level))
        order += 1
    for i, ln in enumerate(lines):
        ln["reading_order"] = i
    rng.shuffle(regions)                     # the reading order decides, not the list
    return upgrade_transcription({"regions": regions, "lines": lines, "steps": [{"step": "layout", "name": "random"}]})


def _legacy_content(doc, region_of) -> list[tuple]:
    """The blocks of a DoclingDocument as the document's blocks would hold them; the text read inside a picture is
    the picture's."""
    from docling_core.types.doc import ContentLayer, PictureItem, SectionHeaderItem, TableItem

    out, picture_of = [], {}
    items = doc.iterate_items(included_content_layers=set(ContentLayer), with_groups=False, traverse_pictures=True)
    for it, _ in items:
        parent = it.parent.cref if it.parent is not None else None
        if parent in picture_of:                                   # text read inside a picture: the picture's own
            k = picture_of[parent]
            kind, text, layer, level, group, grid, _ = out[k]
            origins = (region_of.get(it.self_ref, ":").split(":", 1)[1],
                       *((p.page_no, (p.bbox.l, p.bbox.t, p.bbox.r, p.bbox.b), tuple(p.charspan)) for p in it.prov))
            out[k] = (kind, (text + "\n" if text else "") + it.text, layer, level, group, grid, origins)
            continue
        label = it.label.value
        group, ref = None, parent
        while ref and ref.startswith("#/groups/"):                 # up to the section (a list's group is none)
            g = doc.groups[int(ref.split("/")[-1])]
            if g.label.value == "section":
                group = g.name
                break
            ref = g.parent.cref if g.parent is not None else None
        origins = (region_of.get(it.self_ref, ":").split(":", 1)[1],
                   *((p.page_no, (p.bbox.l, p.bbox.t, p.bbox.r, p.bbox.b), tuple(p.charspan)) for p in it.prov))
        grid = None
        if isinstance(it, TableItem):
            cells = sorted((c.start_row_offset_idx, c.start_col_offset_idx, c.text) for c in it.data.table_cells)
            grid = (it.data.num_rows, it.data.num_cols, tuple(cells))
        level = it.level if isinstance(it, SectionHeaderItem) else None
        if isinstance(it, PictureItem):
            picture_of[it.self_ref] = len(out)
        out.append((KIND.get(label, label), getattr(it, "text", "") or "", it.content_layer.value, level, group, grid,
                    origins))
    return out


def _content(doc) -> list[tuple]:
    """The document's blocks: kind, text, layer, heading level, the heading whose section it is in (as the legacy
    builder names its groups), grid, its first region, and each origin's page, box and characters."""
    by_id = {b.id: b for b in doc.blocks}
    out = []
    for b in doc.blocks:
        section = " ".join(by_id[b.section].text.split())[:80] if b.section else None
        grid = (b.grid.num_rows, b.grid.num_cols, tuple(sorted((c.start_row, c.start_col, c.text)
                                                               for c in b.grid.cells))) if b.grid is not None else None
        origins = (b.origins[0].region if b.origins else "",          # the legacy map names an item's first region
                   *((o.page, tuple(o.box), tuple(o.span)) for o in b.origins if o.box is not None))
        out.append((b.kind, b.text, b.layer, b.level, section, grid, origins))
    return out


def _clipped(block: tuple) -> tuple:
    """The legacy builder counted a division mark it removed in its row's span (``(26, 38)`` then ``(37, ...)``); a
    strategy's span ends where the next row's begins."""
    region, *origins = block[6]
    clipped = [(pg, box, (a, min(e, origins[k + 1][2][0]) if k + 1 < len(origins) else e))
               for k, (pg, box, (a, e)) in enumerate(origins)]
    return (*block[:6], (region, *clipped))


def legacy(pages, text, sections, name="item"):
    b = LegacyDocumentBuilder(name, text=text, sections=sections)
    for t in pages:
        b.add_page(page2(t), 1000, 2000)
    out = _legacy_content(b.build(), b.region_of)
    return [_clipped(x) for x in out] if text == "reflow" else out


def _as_legacy(doc, text):
    """The literal document as the legacy builder wrote it: reflowed, its division marks resolved by squiddleocr's
    rule and the rows flowed (the strategy ``unicode-marks+flow``); laid out, as it is."""
    return apply(doc, "unicode-marks+flow") if text == "reflow" else doc


def ours(pages, text, sections, name="item"):
    pages = [t.model_copy(deep=True) for t in pages]
    ids = [f"p{k}" for k in range(len(pages))]
    if text == "reflow":
        UnicodeParagraphsEngine()(pages, page_ids=ids)
    doc = LinkedDocumentEngine(sections=sections).item_document(pages, name, page_ids=ids,
                                                                  sizes=[(1000, 2000)] * len(pages))
    return _content(_as_legacy(doc, text))


def ours_page(t, text, sections):
    t = t.model_copy(deep=True)
    if text == "reflow":
        UnicodeParagraphsEngine()([t])
    return _content(_as_legacy(LinkedDocumentEngine(sections=sections)(t, name="item", width=1000, height=2000), text))


def two_pages():
    return [page_t(1, ["It was a dark and stormy night when the", "ship left the harbour and turned to"], "CHAPTER I"),
            page_t(2, ["the north, where the ice waited.", "Nobody spoke."])]


FIXTURES = {"sample_transcription": lambda: [sample_transcription()], "page_to_compose": lambda: [page_to_compose()],
            "two_pages": two_pages}


@pytest.mark.parametrize("text", ["lines", "reflow"])
@pytest.mark.parametrize("sections", [False, True])
@pytest.mark.parametrize("fixture", sorted(FIXTURES))
def test_the_fixtures_compose_as_the_legacy_builder_composed_them(fixture, text, sections):
    pages = FIXTURES[fixture]()
    assert ours(pages, text, sections) == legacy(pages, text, sections)
    for t in pages:
        assert ours_page(t, text, sections) == legacy([t], text, sections)


@pytest.mark.parametrize("seed", range(40))
def test_random_items_compose_as_the_legacy_builder_composed_them(seed):
    rng = random.Random(seed)
    pages = [random_page(rng, n) for n in range(rng.randint(1, 5))]
    for text in ("lines", "reflow"):
        for sections in (False, True):
            if sections and text == "reflow" and any(t.label(r.id) == "title" for t in pages for r in t.regions):
                continue                     # the builder it was ported from crashed there; the legacy one is the fix
            assert ours(pages, text, sections) == legacy(pages, text, sections), (seed, text, sections)
            for t in pages:
                assert ours_page(t, text, sections) == legacy([t], text, sections), (seed, text, sections, "page")


def test_random_items_exercise_the_rules():
    """The random pages reach every decision the recomposition makes (else the parity above proves little)."""
    seen = set()
    for seed in range(40):
        rng = random.Random(seed)
        pages = [random_page(rng, n) for n in range(rng.randint(1, 5))]
        for t in UnicodeParagraphsEngine()(pages, page_ids=[str(k) for k in range(len(pages))]):
            seen |= {(d.kind, d.reason) for p in paragraphs(t) for d in p.decisions}
            seen |= {("across pages", "") for p in paragraphs(t)
                     if (ref := t.link(p.id, "continues")) is not None and split_ref(ref)[0] is not None}
    assert {("paragraph_break", "indent"), ("paragraph_break", "gap"), ("paragraph_break", "short_row"),
            ("continuation", "division_mark"),
            ("continuation", "end_margin"), ("across pages", "")} <= seen, seen
