"""The recomposition engine and the Composer against the legacy builder (``legacy_builder``, the DocumentBuilder
as it recomposed while it built, on the page/2 shape of each page: ``legacy_docling.page2``): the same documents
(JSON) and region maps, per page and per item, from lines and from paragraphs, with and without sections, on the
fixtures and on random pages (headings, page numbers, pictures, tables, formulas, indents, gaps, short rows, division
marks of every kind)."""
from __future__ import annotations

import random

import pytest

from conftest import page_t, page_to_compose, sample_transcription
from legacy_builder import LegacyDocumentBuilder
from legacy_docling import page2
from linecaster.data import Transcription
from linecaster.data.upgrade import upgrade_transcription
from linecaster.engines import DoclingCompositionEngine, UnicodeRecompositionEngine
from linecaster.formats.docling import docling_dict
from linecaster.text.recomposition import paragraphs, split_ref

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


def legacy(pages, text, sections, name="item"):
    b = LegacyDocumentBuilder(name, text=text, sections=sections)
    for t in pages:
        b.add_page(page2(t), 1000, 2000)
    return docling_dict(b.build()), b.region_of


def ours(pages, text, sections, name="item"):
    pages = [t.model_copy(deep=True) for t in pages]
    ids = [f"p{k}" for k in range(len(pages))]
    if text == "reflow":
        UnicodeRecompositionEngine()(pages, page_ids=ids)
    doc, region_of = DoclingCompositionEngine(sections=sections).item_document(pages, name, page_ids=ids,
                                                                               sizes=[(1000, 2000)] * len(pages))
    return docling_dict(doc), region_of


def ours_page(t, text, sections):
    t = t.model_copy(deep=True)
    if text == "reflow":
        UnicodeRecompositionEngine()([t])
    doc, region_of = DoclingCompositionEngine(sections=sections)(t, name="item", width=1000, height=2000)
    return docling_dict(doc), region_of


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
        for t in UnicodeRecompositionEngine()(pages, page_ids=[str(k) for k in range(len(pages))]):
            seen |= {(d.kind, d.reason) for p in paragraphs(t) for d in p.decisions}
            seen |= {("across pages", "") for p in paragraphs(t)
                     if (ref := t.link(p.id, "continues")) is not None and split_ref(ref)[0] is not None}
    assert {("mark_removed", "letter_follows"), ("hyphen_kept", "capital_follows"),
            ("hyphen_kept", "digit_follows"), ("hyphen_kept", "no_letter_follows"),
            ("paragraph_break", "indent"), ("paragraph_break", "gap"), ("paragraph_break", "short_row"),
            ("continuation", "division_mark"),
            ("continuation", "end_margin"), ("across pages", "")} <= seen, seen
