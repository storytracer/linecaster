"""Corpus rates from score records, with percentile bootstrap intervals over items."""
from __future__ import annotations

import random
from collections import defaultdict
from typing import Any, Callable, Iterable


def _rate(rows: Iterable[dict], num: Callable[[dict], float], den: Callable[[dict], float]) -> float | None:
    a = b = 0.0
    for r in rows:
        a += num(r)
        b += den(r)
    return a / b if b else None


#: metric -> (numerator, denominator) over score records
RATES: dict[str, tuple[Callable[[dict], float], Callable[[dict], float]]] = {
    "cer": (lambda r: r["s"] + r["d"] + r["i"], lambda r: r["n"]),
    "token_recall": (lambda r: r["words_both"], lambda r: r["words_true"]),
    "over_extraction": (lambda r: r["words_output"] - r["words_both"], lambda r: r["words_output"]),
    # element rows (linecaster.scoring.metrics.score_elements)
    "element_cer": (lambda r: r["s"] + r["d"] + r["i"], lambda r: r["n"]),
    "element_ned": (lambda r: r["s"] + r["d"] + r["i"], lambda r: r["m"]),
    "teds": (lambda r: r["teds"], lambda r: 1),
    "teds_s": (lambda r: r["teds_s"], lambda r: 1),
    "table_recall": (lambda r: 1 if r["as_table"] else 0, lambda r: 1),
    "formula_cer": (lambda r: r["latex_s"] + r["latex_d"] + r["latex_i"], lambda r: r["latex_n"]),
    "formula_ned": (lambda r: r["latex_s"] + r["latex_d"] + r["latex_i"], lambda r: r["latex_m"]),
    # pages' element summaries
    "order_kendall": (lambda r: r["order_discordant"], lambda r: r["order_pairs"]),
    "order_edit": (lambda r: r["order_edits"], lambda r: r["order_len"]),
    "table_precision": (lambda r: r["tables_output_matched"], lambda r: r["tables_output"]),
}


def rates(records: list[dict[str, Any]], metric: str, seed: int = 0, resamples: int = 1000,
          level: float = 0.95) -> dict[str, Any]:
    """The corpus (micro) rate of ``metric`` over ``records`` (rows of one text and lane), and its percentile
    bootstrap interval over items (an item's pages drawn together): ``{value, lo, hi, n}`` (``n``: pages; element
    rows also ``elements``)."""
    num, den = RATES[metric]
    by_item: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_item[r.get("item_id") or r["page_id"]].append(r)
    items = sorted(by_item)
    value = _rate(records, num, den)
    out = {"value": value, "n": len({r["page_id"] for r in records})}
    if records and records[0].get("level") == "element":
        out["elements"] = len(records)
    if resamples and items:
        rnd = random.Random(seed)
        sums = [(sum(num(r) for r in by_item[i]), sum(den(r) for r in by_item[i])) for i in items]
        stats = []
        for _ in range(resamples):
            a = b = 0.0
            for _k in range(len(items)):
                x, y = sums[rnd.randrange(len(items))]
                a += x
                b += y
            if b:
                stats.append(a / b)
        stats.sort()
        if stats:
            lo_k = int((1 - level) / 2 * len(stats))
            hi_k = min(len(stats) - 1, int((1 + level) / 2 * len(stats)))
            out.update(lo=stats[lo_k], hi=stats[hi_k])
    return out


def role_rates(pages: list[dict[str, Any]]) -> dict[str, dict[str, float | None]]:
    """Per content role, the precision and recall of the words the output puts in that role, pooled over pages
    (each page's ``roles`` as ``score_page`` gives it)."""
    tot: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for p in pages:
        for role, c in p.items():
            t = tot[role]
            t[0] += c["true"]
            t[1] += c["output"]
            t[2] += c["both"]
    return {role: {"precision": b / o if o else None, "recall": b / t if t else None}
            for role, (t, o, b) in sorted(tot.items())}
