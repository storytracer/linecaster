"""Shared fixtures and helpers: the sample transcription (``linecaster.testing``), regions and lines by their boxes,
and page documents for the blocks; linecaster's markers and the hooks that skip ``gpu`` and ``network`` tests where
they cannot run (``linecaster.testing.markers``)."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from linecaster.blocks.base.page import new_page_document, page_of, set_page
from linecaster.data import Transcription
from linecaster.data.upgrade import upgrade_transcription
from linecaster.testing import box, sample_transcription
from linecaster.testing.markers import pytest_collection_modifyitems, pytest_configure  # noqa: F401 - the hooks


@pytest.fixture(autouse=True)
def vendor_requests_for_adapters(request, monkeypatch):
    """Under ``tests/adapters`` requests are compared with the model vendors' (cards, reference scripts), which do not
    send vLLM's ``repetition_detection``: the module's ``chat_model`` builds adapters with it off unless a test sets it
    (``tests/blocks/recognition/test_repetition_detection.py`` covers it, on by default)."""
    chat_model = getattr(request.module, "chat_model", None)
    if "adapters" not in request.node.path.parts or chat_model is None:
        return

    def without_detection(*args, overrides=None, **kwargs):
        return chat_model(*args, overrides={"repetition_detection": False, **(overrides or {})}, **kwargs)

    monkeypatch.setattr(request.module, "chat_model", without_detection)


@pytest.fixture(autouse=True)
def pillow_decoding_for_adapters(request):
    """The adapters' requests are compared with their reference scripts' own, which decode with Pillow: under
    ``tests/adapters`` pages are decoded with Pillow (``image_decode`` ``cpu``); ``tests/images/test_pixels.py``
    covers the GPU."""
    if "adapters" not in request.node.path.parts:
        yield
        return
    from linecaster.images import pixels

    before = pixels.decoding()
    pixels.set_decoding("cpu")
    yield
    pixels.set_decoding(*before)


@pytest.fixture
def transcription() -> Transcription:
    return sample_transcription()


# ------------------------------------------------------------------ regions, lines and pages by their boxes
# Regions and lines are written as page/2 dicts (label, reading order and row on them) and become a transcription
# through the upgrade (``page_with``): one annotator, a role per label, one reading order.
def region(rid, label, x, y, w, h, order, raw=None, **kw):
    return {"id": rid, "label": label, "raw_label": raw or label, "polygon": box(x, y, w, h), "bbox": [x, y, w, h],
            "score": 0.9, "reading_order": order, **kw}


def line(rid, k, x, y, w, h, text, row=None, conf=0.99):
    return {"id": f"{rid}_l{k}", "region_id": rid, "row": k if row is None else row, "polygon": box(x, y, w, h),
            "bbox": [x, y, w, h], "text": text, "confidence": conf}


def body_region(rid, order, y0, n=6, h=20, x=100, prefix="body"):
    r = region(rid, "text", x, y0, 800, n * (h + 10), order)
    return r, [line(rid, k, x, y0 + k * (h + 10), 800, h, f"{prefix} {k}") for k in range(n)]


def page_with(regions, lines, **fields) -> Transcription:
    """A transcription of page/2-style regions and lines (``region``, ``line``), by one annotator (step ``layout``)."""
    return upgrade_transcription({"regions": regions, "lines": lines, "steps": [{"step": "layout", "name": "test"}],
                                  **fields})


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
    return page_with(regions, lines)


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
