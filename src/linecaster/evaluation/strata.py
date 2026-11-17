"""Rates by strata: a run's rates read on part of a benchmark, by a dimension of what was compared. Element rates are
always given by ``role`` and ``kind``; a benchmark's ``strata`` add dimensions:

* of an element (``linecaster.evaluation.elements``): ``role``, ``kind``, ``layer``, ``match`` (its group's kind),
  ``table_kind``, and any scheme it records (``language``, ``script``, ``direction``: the writing system that holds for
  it; its region's classifications: a tag such as ``degraded``);
* of a page: ``slice`` (``linecaster.evaluation.slices``) and any scheme the page records (its ``""`` classifications:
  ``language``, ``script``, ``direction``, a tag), for the page-level rates too.

Only recorded values count: an element or page without one is in the stratum ``unrecorded``, never given an
inferred value.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

#: dimensions an element row holds as fields
ELEMENT_FIELDS = ("role", "kind", "layer", "match", "table_kind")
#: the stratum of what records no value
UNRECORDED = "unrecorded"


def element_value(row: dict[str, Any], dim: str, page: dict[str, Any] | None = None) -> str:
    """The stratum of an element row in dimension ``dim``."""
    if dim in ELEMENT_FIELDS:
        value = row.get(dim)
    else:
        value = next((v for s, v in (row.get("attributes") or []) if s == dim), None)
        if value is None and page is not None:
            value = (page.get("strata") or {}).get(dim)
    return str(value) if value not in (None, "") else UNRECORDED


def page_values(page: dict[str, Any], dim: str) -> list[str]:
    """The strata of a page (its summary, ``score_pair``) in dimension ``dim``: its slices, or its recorded value."""
    if dim == "slice":
        return list(page.get("slices") or ()) or [UNRECORDED]
    value = (page.get("strata") or {}).get(dim)
    return [str(value)] if value not in (None, "") else [UNRECORDED]


def page_strata(gt) -> dict[str, str]:
    """A ground-truth page's recorded values (its ``""`` classifications, the writing system through
    ``Transcription.written``), by scheme: what page strata read."""
    out: dict[str, str] = {}
    for c in gt.classifications:
        if c.target == "" and c.scheme not in out:
            out[c.scheme] = str(c.value)
    for scheme in ("language", "script", "direction"):
        value = getattr(gt, scheme)("") if hasattr(gt, scheme) else None
        if value:
            out[scheme] = str(value)
    return out


def group(rows: list[dict[str, Any]], dim: str, pages: dict[str, dict[str, Any]] | None = None,
          element: bool = True) -> dict[str, list[dict[str, Any]]]:
    """``rows`` by their stratum in ``dim``: element rows by ``element_value``, page rows by ``page_values`` (a page
    in several slices is in each)."""
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        page = (pages or {}).get(r["page_id"])
        if element and dim != "slice":
            out[element_value(r, dim, page)].append(r)
        else:
            for value in page_values(page or {}, dim):
                out[value].append(r)
    return dict(sorted(out.items()))


__all__ = ["ELEMENT_FIELDS", "UNRECORDED", "element_value", "group", "page_strata", "page_values"]
