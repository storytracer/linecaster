"""Shared fixtures and helpers: a realistic transcription exercising every serializer feature, regions and lines
by their boxes, and page documents for the blocks."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from linecaster.blocks.base.page import new_page_document, page_of, set_page
from linecaster.data import Line, Region, Source, Transcription, Word


def make_transcription() -> Transcription:
    regions = [
        Region(id="page_header_0", label="page_header", raw_label="header", reading_order=0,
               polygon=[[120.0, 80.0], [1480.0, 80.0], [1480.0, 140.0], [120.0, 140.0]],
               bbox=[120.0, 80.0, 1360.0, 60.0], score=0.91),
        Region(id="doc_title_1", label="title", raw_label="doc_title", reading_order=1,
               polygon=[[300.4, 200.2], [1300.7, 198.9], [1302.1, 330.5], [298.0, 331.6]],
               bbox=[298.0, 198.9, 1004.1, 132.7], score=0.873, heading_level=1),
        Region(id="text_2", label="text", raw_label="text", reading_order=2,
               polygon=[[118.0, 400.0], [1490.5, 400.0], [1490.5, 700.25], [118.0, 700.25]],
               bbox=[118.0, 400.0, 1372.5, 300.25], score=0.95),
        Region(id="image_3", label="picture", raw_label="image", reading_order=3,
               polygon=[[200.0, 760.0], [1400.0, 760.0], [1400.0, 1500.0], [200.0, 1500.0]],
               bbox=[200.0, 760.0, 1200.0, 740.0], score=0.88),
        Region(id="footnote_4", label="footnote", raw_label="footnote", reading_order=4,
               polygon=[[120.0, 1900.0], [1480.0, 1900.0], [1480.0, 2000.0], [120.0, 2000.0]],
               bbox=[120.0, 1900.0, 1360.0, 100.0]),
    ]
    lines = [
        Line(id="l0", region_id="page_header_0", reading_order=0, row=0, bbox=[130.0, 85.0, 400.0, 50.0],
             baseline=[[130.0, 125.0], [530.0, 126.0]], text="12 THE BOTANIST", confidence=0.97,
             words=[Word(id="l0_w0", text="12", bbox=[130.0, 86.0, 40.0, 40.0], confidence=0.99),
                    Word(id="l0_w1", text="THE", bbox=[190.0, 86.0, 90.0, 40.0], confidence=0.96),
                    Word(id="l0_w2", text="BOTANIST", bbox=[300.0, 86.0, 230.0, 40.0], confidence=0.95)]),
        Line(id="l1", region_id="doc_title_1", reading_order=1, row=0, bbox=[310.25, 210.5, 980.5, 110.75],
             polygon=[[310.25, 210.5], [1290.75, 209.0], [1290.75, 321.25], [310.25, 322.0]],
             baseline=[[312.5, 300.25], [800.0, 301.5], [1288.0, 302.75]], score=0.8125,
             text="Flora of the Northern Hills", confidence=0.884,
             words=[Word(id="l1_w0", text="Flora", bbox=[312.0, 215.0, 200.0, 100.0], confidence=0.9),
                    Word(id="l1_w1", text="of", bbox=[530.0, 215.0, 70.0, 100.0], confidence=0.8),
                    Word(id="l1_w2", text="the", bbox=[620.0, 215.0, 120.0, 100.0], confidence=0.85),
                    Word(id="l1_w3", text="Northern", bbox=[760.0, 215.0, 300.0, 100.0], confidence=0.9),
                    Word(id="l1_w4", text="Hills", bbox=[1080.0, 215.0, 200.0, 100.0], confidence=0.88,
                         alternatives=["Hilis"])]),
        Line(id="l2", region_id="text_2", reading_order=2, row=0, bbox=[120.0, 405.0, 1360.0, 60.0],
             polygon=[[120.0, 405.0], [1480.0, 405.0], [1480.0, 465.0], [120.0, 465.0]],
             baseline=[[120.0, 455.0], [1480.0, 455.0]],
             text="The species described here were col-", confidence=0.93,
             words=[Word(id="l2_w0", text="The", bbox=[120.0, 410.0, 80.0, 50.0], confidence=0.99),
                    Word(id="l2_w1", text="species", bbox=[215.0, 410.0, 170.0, 50.0], confidence=0.97),
                    Word(id="l2_w2", text="described", bbox=[400.0, 410.0, 220.0, 50.0], confidence=0.95),
                    Word(id="l2_w3", text="here", bbox=[635.0, 410.0, 100.0, 50.0], confidence=0.9),
                    Word(id="l2_w4", text="were", bbox=[750.0, 410.0, 110.0, 50.0], confidence=0.92),
                    Word(id="l2_w5", text="col-", bbox=[875.0, 410.0, 90.0, 50.0], confidence=0.71,
                         hyphen=True)]),
        # boxes only, recognized: no polygon, no baseline, no words
        Line(id="l3", region_id="text_2", reading_order=3, row=1, bbox=[120.0, 475.0, 1300.0, 60.0],
             text="lected in the summer of 1887 by the author.", confidence=0.9),
        # empty text line (recognized as empty)
        Line(id="l4", region_id="text_2", reading_order=4, row=2, bbox=[120.0, 545.0, 1300.0, 60.0],
             baseline=[[120.0, 595.0], [1420.0, 595.0]], text="", confidence=0.5),
        # not recognized yet (text None)
        Line(id="l5", region_id="text_2", reading_order=5, row=3, bbox=[120.0, 615.0, 1300.0, 60.0],
             polygon=[[120.0, 615.0], [1420.0, 615.0], [1420.0, 675.0], [120.0, 675.0]]),
        # a line without a region (an orphan row from the line step)
        Line(id="orphan_0", region_id=None, reading_order=6, row=0, bbox=[1500.0, 1600.0, 80.0, 300.0],
             baseline=[[1540.0, 1600.0], [1540.0, 1900.0]], text="Plate IV", confidence=0.66,
             words=[Word(id="orphan_0_w0", text="Plate", bbox=[1500.0, 1600.0, 80.0, 180.0], confidence=0.7),
                    Word(id="orphan_0_w1", text="IV", bbox=[1500.0, 1800.0, 80.0, 100.0], confidence=0.6)]),
        Line(id="l7", region_id="footnote_4", reading_order=7, row=0, bbox=[130.0, 1910.0, 1000.0, 40.0],
             baseline=[[130.0, 1945.0], [1130.0, 1945.0]], text="1 See  Gray, Manual.", confidence=0.8,
             words=[Word(id="l7_w0", text="1", bbox=[130.0, 1912.0, 20.0, 36.0]),
                    Word(id="l7_w1", text="See", bbox=[160.0, 1912.0, 70.0, 36.0], confidence=0.85),
                    Word(id="l7_w2", text="Gray,", bbox=[250.0, 1912.0, 110.0, 36.0], confidence=0.83),
                    Word(id="l7_w3", text="Manual.", bbox=[375.0, 1912.0, 160.0, 36.0], confidence=0.77)]),
    ]
    return Transcription(regions=regions, lines=lines,
                         source=Source(image_width=1600, image_height=2400, uri="page_0001.webp"))


@pytest.fixture
def transcription() -> Transcription:
    return make_transcription()


# ------------------------------------------------------------------ regions, lines and pages by their boxes
def box(x, y, w, h):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def region(rid, label, x, y, w, h, order, raw=None, **kw):
    return Region(id=rid, label=label, raw_label=raw or label, polygon=box(x, y, w, h), bbox=[x, y, w, h],
                  score=0.9, reading_order=order, **kw)


def line(rid, k, x, y, w, h, text, row=None, conf=0.99):
    return Line(id=f"{rid}_l{k}", region_id=rid, row=k if row is None else row, polygon=box(x, y, w, h),
                bbox=[x, y, w, h], text=text, confidence=conf)


def body_region(rid, order, y0, n=6, h=20, x=100, prefix="body"):
    r = region(rid, "text", x, y0, 800, n * (h + 10), order)
    return r, [line(rid, k, x, y0 + k * (h + 10), 800, h, f"{prefix} {k}") for k in range(n)]


def page_with(regions, lines):
    return Transcription(regions=regions, lines=lines)


def page_to_compose():
    b, bl = body_region("text_1", 1, 300)
    t = page_with([
        region("doc_title_0", "title", 100, 100, 800, 60, 0),
        b,
        region("number_2", "page_footer", 450, 900, 40, 20, 2, raw="number"),
        region("table_3", "table", 100, 600, 800, 200, 3,
               extra={"table": {"num_rows": 2, "num_cols": 2, "html": None, "cells": [
                   {"text": "a", "row": 0, "col": 0, "row_span": 1, "col_span": 1, "bbox": [100, 600, 400, 100], "header": True},
                   {"text": "b", "row": 0, "col": 1, "row_span": 1, "col_span": 1, "bbox": None, "header": True},
                   {"text": "c", "row": 1, "col": 0, "row_span": 1, "col_span": 1, "bbox": None, "header": False},
                   {"text": "d", "row": 1, "col": 1, "row_span": 1, "col_span": 1, "bbox": None, "header": False}]}}),
        region("image_4", "picture", 100, 820, 300, 60, 4),
        region("text_5", "text", 100, 890, 300, 5, 5),          # no lines: no item
        region("section_header_6", "section_header", 100, 850, 800, 40, None, heading_level=2),
    ], [line("doc_title_0", 0, 100, 100, 800, 60, "THE TITLE"), *bl,
        line("number_2", 0, 450, 900, 40, 20, "12"),
        line("image_4", 0, 100, 820, 140, 20, "Fig. 1", row=0), line("image_4", 1, 250, 820, 140, 20, "left", row=0),
        line("section_header_6", 0, 100, 850, 800, 40, "LAST")])
    return t


def page_t(n: int, body: list[str], heading: str | None = None):
    regions, lines = [], []
    if heading:
        regions.append(region("section_header_0", "section_header", 100, 50, 800, 40, 0, heading_level=2))
        lines.append(line("section_header_0", 0, 100, 50, 800, 40, heading))
    rid = "text_1"
    regions.append(region(rid, "text", 100, 100, 800, 30 * len(body), 1))
    lines += [line(rid, k, 100, 100 + 30 * k, 800, 20, s) for k, s in enumerate(body)]
    regions.append(region("number_2", "page_footer", 450, 900, 40, 20, 2, raw="number"))
    lines.append(line("number_2", 0, 450, 900, 40, 20, str(n)))
    return Transcription(regions=regions, lines=lines)


def page_doc(page_id="p1", item="book1", t: Transcription | None = None, seq=1):
    buf = io.BytesIO()
    Image.new("RGB", (1000, 1000), "white").save(buf, format="PNG")
    doc = new_page_document(page_id, buf.getvalue(), uri=f"/scans/{page_id}.png", item_id=item, sequence=seq)
    page = page_of(doc)
    page.transcriptions["ocr_new"] = t if t is not None else page_to_compose()
    set_page(doc, page, "ocr_new")
    return doc


def recomposed(t: Transcription, **options) -> Transcription:
    """``t`` with its paragraphs (the recomposition engine on the page alone), for composing it as running text."""
    from linecaster.engines import UnicodeRecompositionEngine

    UnicodeRecompositionEngine(**options)([t])
    return t


def item_variants(pages: list[Transcription]) -> dict[str, str]:
    """The text variants of consecutive pages (an item) as the item stage makes them: recomposed as one item,
    normalized (``latin-historic``), rendered (``linecaster.text.variants.variants``)."""
    from linecaster.engines import LatinHistoricNormalizationEngine, UnicodeRecompositionEngine
    from linecaster.text.variants import variants

    UnicodeRecompositionEngine()(pages)
    for t in pages:
        LatinHistoricNormalizationEngine()(t)
    return variants(pages)
