"""The hand-written ``linecaster.page/3`` fixtures (``tests/data/page3``): every reference in them resolves by the
data model's reference grammar, and every character span lies inside the text it names. The fixtures hold the
ground-truth cases the model has to express (``README.md`` there); the model's classes validate them once they
exist."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

HERE = Path(__file__).parent / "page3"
PAGES = {p["id"]: p["page"] for p in (json.loads(f.read_text(encoding="utf-8")) for f in HERE.glob("*.json"))}
REF = re.compile(r"^(?:(?P<page>[^#]+)#)?(?P<id>[^/\[#]*)(?:/(?P<word>\d+)(?:/(?P<glyph>\d+))?)?"
                 r"(?:\[(?P<start>\d+):(?P<end>\d+)\])?$")


def _text(aset: dict, zone_id: str) -> str | None:
    for ln in aset.get("lines", []):
        if ln["id"] == zone_id:
            return (ln.get("reading") or {}).get("text")
    for rg in aset.get("ranges", []):
        if rg["id"] == zone_id:
            return rg.get("text")
    return None


def _resolve(page: dict, set_name: str, ref: str) -> None:
    m = REF.match(ref)
    assert m, f"not a reference: {ref!r}"
    if m["page"]:
        assert m["page"] in PAGES, f"{ref!r}: no page {m['page']!r}"
        page = PAGES[m["page"]]
    aset = page["transcriptions"].get(set_name) or page["annotations"][set_name]
    if m["id"] == "":
        return                                               # the page
    ids = {z["id"] for k in ("regions", "lines", "ranges") for z in aset.get(k, [])}
    assert m["id"] in ids, f"{ref!r}: no zone or range {m['id']!r}"
    if m["start"] is not None:
        text = _text(aset, m["id"])
        assert text is not None and int(m["start"]) < int(m["end"]) <= len(text), f"{ref!r}: span outside the text"


def _refs(aset: dict):
    for kind in ("classifications", "edits", "descriptions", "tables", "formulas"):
        for a in aset.get(kind, []):
            yield a["target"]
            yield from a.get("derived_from", [])
    for a in aset.get("links", []):
        yield a["source"]
        yield a["target"]
    for o in aset.get("orders", []):
        yield from o.get("regions", [])
        yield from o.get("lines", [])
    for z in aset.get("regions", []) + aset.get("lines", []):
        if z.get("parent"):
            yield z["parent"]
        if z.get("region"):
            yield z["region"]
    for r in aset.get("ranges", []):
        yield from r.get("parts", [])
        for row in r.get("rows", []):
            yield from row["lines"]


@pytest.mark.parametrize("page_id", sorted(PAGES))
def test_every_reference_resolves(page_id):
    page = PAGES[page_id]
    for name, aset in {**page.get("transcriptions", {}), **page.get("annotations", {})}.items():
        n = len(aset["annotators"])
        for kind, items in aset.items():
            if isinstance(items, list) and kind not in ("annotators", "outputs"):
                assert all(0 <= a.get("annotator", 0) < n for a in items), (name, kind)
        for ref in _refs(aset):
            _resolve(page, name, ref)


def test_a_paragraph_continued_onto_the_next_page_is_linked_both_ways():
    from linecaster.data import Page

    pages = {pid: Page.model_validate(p) for pid, p in PAGES.items()}
    first, second = (pages[f"library.test_item1_{n:04d}"].transcriptions["ground_truth"] for n in (12, 13))
    assert first.link("r2_p0", "runs_into") == "library.test_item1_0013#r2_p0"
    assert second.link("r2_p0", "continues") == "library.test_item1_0012#r2_p0"
    for t in (first, second):
        for p in t.paragraphs:
            for row in p.rows:
                assert 0 <= row.charspan[0] < row.charspan[1] <= len(p.text)


@pytest.mark.parametrize("page_id", sorted(PAGES))
def test_the_fixtures_are_valid_page_records(page_id):
    from linecaster.data import Page

    page = Page.model_validate(PAGES[page_id])
    assert page.record() == Page.model_validate(page.record()).record()
