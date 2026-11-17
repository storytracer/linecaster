"""Scoring a run: its page records against a ground truth's, by a benchmark, into score records and corpus rates.

``score_run(run, truth, benchmark)`` reads both folders of page records (JSON Lines, gzipped or not, or Parquet, as
linecaster's page writers write them; older formats upgraded), pairs the pages of the benchmark's page set by page
id, and scores each. A page the run lacks or failed counts as an empty output and is counted (``missing``,
``failed``); a run that lacks pages is not eligible.
"""
from __future__ import annotations

import gzip
import json
import re
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from linecaster.data.page import Page
from linecaster.data.policy import DEFAULT_POLICY, RenderingPolicy
from linecaster.data.sample import listing_sha256
from linecaster.data.upgrade import upgrade
from linecaster.evaluation.aggregate import rates, role_rates
from linecaster.evaluation.benchmark import Benchmark
from linecaster.evaluation.metrics import score_elements, score_page
from linecaster.evaluation.slices import SLICES
from linecaster.evaluation.strata import group as strata_group, page_strata

SCORE_SCHEMA = "linecaster.score/1"


class ConventionsWarning(UserWarning):
    """A lane does not apply a normalization the ground truth declares it embodies (``score_run``'s conventions
    check)."""


def read_records(folder: str | Path) -> Iterator[dict]:
    """The stored rows (``{"schema", "id", "text", "page", "errors"?}``) of a folder of page records, upgraded."""
    folder = Path(folder)
    for f in sorted(p for p in folder.rglob("*") if p.is_file()):
        if f.name.endswith((".jsonl", ".jsonl.gz")):
            opener = gzip.open if f.name.endswith(".gz") else open
            with opener(f, "rt", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        yield upgrade(json.loads(line))
        elif f.suffix == ".parquet":
            import pyarrow.parquet as pq

            for row in pq.read_table(f).to_pylist():
                for key in ("page", "errors"):
                    if isinstance(row.get(key), str):
                        row[key] = json.loads(row[key])
                yield upgrade(row)


def scorer() -> str:
    from linecaster.evaluation import scorer as named

    return named()


def score_pair(pid: str, truth_row: dict, out_row: dict | None, benchmark: Benchmark,
               transcription: str = "ocr_new", policy: RenderingPolicy = DEFAULT_POLICY,
               run_id: str | None = None) -> tuple[list[dict], dict]:
    """One page of the benchmark scored: its ground truth's row against the run's (``None``: the run lacks it, an
    empty output). Returns the page's score records (one per text and lane) and its summary (``page_id``,
    ``item_id``, ``roles``, ``confusion``, and ``missing`` and ``failed``)."""
    truth_page = Page.model_validate(truth_row["page"])
    gt = truth_page.transcriptions[benchmark.dataset.transcription]
    out = None
    flags = {"missing": out_row is None, "error": None, "finish_reason": None}
    if out_row is not None:
        page = Page.model_validate(out_row["page"])
        out = page.transcriptions.get(transcription)
        if out_row.get("errors"):
            flags["error"] = "; ".join(str(e.get("error", e)) for e in out_row["errors"]) if isinstance(
                out_row["errors"], list) else str(out_row["errors"])
            out = None
        elif out is not None and out.annotators:
            flags["finish_reason"] = next((a.measurements.get("finish_reason") for a in reversed(out.annotators)
                                           if "finish_reason" in a.measurements), None)
    roles = bool(benchmark.supports.roles) and "role_words" in benchmark.metrics
    got = score_page(gt, out, benchmark.texts, benchmark.lanes, policy, boxes="confusion" in benchmark.metrics,
                     unit=benchmark.unit, strategy=benchmark.output, tokenizer=benchmark.words)
    item_id = truth_page.item_id
    records = [{"schema": SCORE_SCHEMA, "page_id": pid, "item_id": item_id, **r, **flags, "run_id": run_id,
                "benchmark": benchmark.ref, "benchmark_sha256": benchmark.sha256, "policy": policy.ref,
                "output": benchmark.output, "scorer": scorer()} for r in got["rows"]]
    from linecaster.evaluation.slices import page_slices

    summary = {"page_id": pid, "item_id": item_id, "roles": got["roles"] if roles else {},
               "confusion": got.get("confusion", []), "missing": out_row is None,
               "failed": flags["error"] is not None, "slices": page_slices(gt), "strata": page_strata(gt)}
    if benchmark.element_metrics:
        el = score_elements(gt, out, benchmark.texts, benchmark.lanes, policy, benchmark.unit, benchmark.output,
                            benchmark.elements.matching(), benchmark.elements.tables, benchmark.elements.lane)
        records += [{"schema": SCORE_SCHEMA, "page_id": pid, "item_id": item_id, **r, **flags, "run_id": run_id,
                     "benchmark": benchmark.ref, "benchmark_sha256": benchmark.sha256, "policy": policy.ref,
                     "output": benchmark.output, "scorer": scorer()} for r in el["rows"]]
        summary["elements"] = el["page"]
    return records, summary


def summarize(records: list[dict], pages: list[dict], benchmark: Benchmark, warn: bool = True) -> dict[str, Any]:
    """The run's result from its pages' score records and summaries (``score_pair``'s, every page of the benchmark
    once): ``rates`` (metric name -> value, interval, ``n``), ``roles`` (per role precision and recall), the counts
    ``pages_scored``, ``missing``, ``failed`` and ``eligible``, ``conventions`` (lane -> the ground truth's
    declared normalizations it does not apply, on any page: the conventions check; each one warned of), and
    ``slices`` (``linecaster.evaluation.slices``: per slice its definition, pages and the rates on its pages; empty for
    page summaries written before 0.10.4, which name no slices)."""
    b = benchmark.bootstrap
    by: dict[tuple[str, str], list[dict]] = {}
    for r in records:
        if r.get("level") != "element":
            by.setdefault((r["text"], r["lane"]), []).append(r)
    out_rates: dict[str, Any] = {}
    for name in benchmark.texts:
        for ln in benchmark.lanes:
            sel = by.get((name, ln), [])
            for metric in ("cer", "token_recall", "over_extraction"):
                if metric in benchmark.metrics:
                    out_rates[f"{metric}_{name}_{ln}"] = rates(sel, metric, b.seed, b.resamples, b.level)
    slices: dict[str, Any] = {}
    in_slice: dict[str, set[str]] = {}
    for p in pages:
        for name in p.get("slices") or ():
            in_slice.setdefault(name, set()).add(p["page_id"])
    for name in (n for n in SLICES if n in in_slice):
        ids, sl_rates = in_slice[name], {}
        for text_name in benchmark.texts:
            for ln in benchmark.lanes:
                sel = [r for r in by.get((text_name, ln), []) if r["page_id"] in ids]
                for metric in ("cer", "token_recall"):
                    if metric in benchmark.metrics:
                        sl_rates[f"{metric}_{text_name}_{ln}"] = rates(sel, metric, b.seed, b.resamples, b.level)
        slices[name] = {"definition": SLICES[name], "pages": len(ids), "rates": sl_rates}
    conventions: dict[str, list[str]] = {}
    for r in records:
        if r.get("conventions"):
            conventions[r["lane"]] = sorted(set(conventions.get(r["lane"], [])) | set(r["conventions"]))
    if warn:
        for ln, missing_n in conventions.items():
            warnings.warn(f"lane {ln}: the ground truth already applies {', '.join(missing_n)} (its conventions), "
                          f"the lane does not: the output's differences there are counted as errors",
                          ConventionsWarning, stacklevel=3)
    if benchmark.element_metrics:
        el_rates, el_strata = _element_results(records, pages, benchmark)
        out_rates.update(el_rates)
    else:
        el_strata = {}
    strata = {**el_strata, **_page_strata(by, pages, benchmark)}
    roles = bool(benchmark.supports.roles) and "role_words" in benchmark.metrics
    missing = sum(1 for p in pages if p.get("missing"))
    failed = sum(1 for p in pages if p.get("failed"))
    return {"records": records, "pages": pages, "rates": out_rates, "slices": slices, "strata": strata,
            "conventions": conventions,
            "roles": role_rates([p["roles"] for p in pages]) if roles else {},
            "pages_scored": len(pages), "missing": missing, "failed": failed, "eligible": missing == 0}


#: element rates by metric: (rate, the rows it is over)
_ELEMENT_RATES = {
    "elements": (("element_cer", None), ("element_ned", None)),
    "tables": (("teds", "table"), ("teds_s", "table"), ("table_recall", "table")),
}


def _element_results(records: list[dict], pages: list[dict], benchmark: Benchmark) -> tuple[dict, dict]:
    """The element rates (``score_elements``' rows and the pages' ``elements`` summaries) and their strata: by role
    and kind always, and by the benchmark's ``strata``."""
    b = benchmark.bootstrap
    rows = [r for r in records if r.get("level") == "element"]
    by: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        by.setdefault((r["text"], r["lane"]), []).append(r)
    out: dict[str, Any] = {}

    def rated(sel: list[dict], into: dict, suffix: str) -> None:
        for metric, needs in (x for m in ("elements", "tables") if m in benchmark.metrics for x in _ELEMENT_RATES[m]):
            chosen = [r for r in sel if r["side"] == "truth" and r["kind"] == needs] if needs else sel
            if chosen:
                into[f"{metric}{suffix}"] = rates(chosen, metric, b.seed, b.resamples, b.level)

    for name in benchmark.texts:
        for ln in benchmark.lanes:
            rated(by.get((name, ln), []), out, f"_{name}_{ln}")
    first = by.get((benchmark.texts[0], benchmark.lanes[0]), []) if benchmark.texts and benchmark.lanes else []
    if "formulas" in benchmark.metrics:
        formulas = [r for r in first if r["side"] == "truth" and r["kind"] == "formula"]
        if formulas:
            for metric in ("formula_cer", "formula_ned"):
                out[metric] = rates(formulas, metric, b.seed, b.resamples, b.level)
    summaries = [{"page_id": p["page_id"], "item_id": p.get("item_id"), **p["elements"]} for p in pages
                 if p.get("elements")]
    if "tables" in benchmark.metrics and any(s["tables_output"] for s in summaries):
        out["table_precision"] = rates(summaries, "table_precision", b.seed, b.resamples, b.level)
    if "reading_order" in benchmark.metrics and summaries:
        for metric in ("order_kendall", "order_edit"):
            out[metric] = rates(summaries, metric, b.seed, b.resamples, b.level)
    by_page = {p["page_id"]: p for p in pages}
    strata: dict[str, Any] = {}
    for dim in dict.fromkeys(["role", "kind", *benchmark.strata]):
        if dim == "slice":
            continue
        groups = strata_group(first, dim, by_page)
        strata[dim] = {}
        for value, sel in groups.items():
            got: dict[str, Any] = {}
            rated(sel, got, "")
            strata[dim][value] = {"pages": len({r["page_id"] for r in sel}), "elements": len(sel), "rates": got}
    return out, strata


def _page_strata(by: dict[tuple[str, str], list[dict]], pages: list[dict], benchmark: Benchmark) -> dict:
    """The page-level rates (CER, word recall) by the benchmark's page strata: ``slice`` and recorded schemes."""
    b = benchmark.bootstrap
    by_page = {p["page_id"]: p for p in pages}
    first = by.get((benchmark.texts[0], benchmark.lanes[0]), []) if benchmark.texts and benchmark.lanes else []
    out: dict[str, Any] = {}
    for dim in benchmark.strata:
        if dim in ("role", "kind", "layer", "match", "table_kind"):
            continue
        groups = strata_group(first, dim, by_page, element=False)
        key = f"pages:{dim}"
        out[key] = {}
        for value, sel in groups.items():
            got = {m: rates(sel, m, b.seed, b.resamples, b.level) for m in ("cer", "token_recall")
                   if m in benchmark.metrics and sel}
            out[key][value] = {"pages": len({r["page_id"] for r in sel}), "elements": 0, "rates": got}
    return out


def wanted_pages(benchmark: Benchmark, truths=None) -> list[str]:
    """The benchmark's page set, checked against its hash: its ids; else its sample rule (``linecaster.data.sample``)
    applied to the ground truth, ``truths`` its rows by id or the folder of its page records (a rule that
    ``stratify``s by the pages' values, ``linecaster.evaluation.truth.page_values``); else every ground-truth page."""
    ps = benchmark.pages
    if ps.ids is not None:
        wanted = ps.ids
    elif ps.rule is not None and truths is not None:
        wanted = _sampled(ps.rule, truths, benchmark.dataset.transcription)
    else:
        wanted = sorted(truths or ())
    if listing_sha256(wanted) != ps.sha256:
        raise ValueError(f"the ground truth's pages are not the benchmark's page set ({ps.sha256})")
    return wanted


def _sampled(rule: dict, truths, transcription: str) -> list[str]:
    from linecaster.data.page import Page
    from linecaster.data.sample import SampleRule, sample_pairs
    from linecaster.evaluation.truth import page_values, read_rows

    rows = truths.values() if isinstance(truths, dict) else read_rows(str(truths))
    pairs, strata = [], {}
    r = SampleRule(**{k: v for k, v in rule.items() if v is not None})
    for row in rows:
        page = Page.model_validate(row["page"])
        pairs.append((page.item_id, row["id"]))
        if r.stratify:
            strata[row["id"]] = page_values(page, r.stratify, transcription)
    return [s.page_id for s in sample_pairs(pairs, r, strata if r.stratify else None).selected]


def score_run(run: str | Path, truth: str | Path, benchmark: Benchmark, transcription: str = "ocr_new",
              policy: RenderingPolicy = DEFAULT_POLICY, run_id: str | None = None) -> dict[str, Any]:
    """Scores the run's page records against the ground truth's, in this process (``score_pair`` for each page of
    the benchmark, then ``summarize``); ``pipelines/score.py`` does the same over many tasks. Returns
    ``summarize``'s result: ``records`` (score records), ``pages`` (per page: ``page_id``, ``item_id``, ``roles``,
    ``confusion``), ``rates``, ``roles``, ``pages_scored``, ``missing``, ``failed``, ``eligible``, ``conventions``."""
    if policy.ref != benchmark.policy:
        raise ValueError(f"the benchmark renders with {benchmark.policy}, not {policy.ref}")
    truths = {r["id"]: r for r in read_records(truth)}
    wanted = wanted_pages(benchmark, truths)
    want = set(wanted)
    outputs = {r["id"]: r for r in read_records(run) if r["id"] in want}
    records, pages = [], []
    for pid in wanted:
        tr = truths.get(pid)
        if tr is None:
            raise ValueError(f"page {pid} of the page set is not in the ground truth")
        recs, summary = score_pair(pid, tr, outputs.get(pid), benchmark, transcription, policy, run_id)
        records += recs
        pages.append(summary)
    return summarize(records, pages, benchmark)


#: a record's id near the start of its line (linecaster's writers put ``schema`` and ``id`` first)
_ID = re.compile(r'"id":\s*"((?:[^"\\]|\\.)*)"')


def truth_ids(folder: str) -> set[str]:
    """Every page id in a folder of page records (local path or fsspec URI; JSON Lines, gzipped or not), read from
    each line's start without decoding the line."""
    from datatrove.io import get_datafolder

    df = get_datafolder(folder)
    found: set[str] = set()
    for name in df.list_files(glob_pattern="**/*.jsonl*"):
        with df.open(name, "rt", compression="gzip" if name.endswith(".gz") else None, encoding="utf-8") as fh:
            for line in fh:
                m = _ID.search(line, 0, 400)
                if m:
                    found.add(json.loads(f'"{m.group(1)}"'))
    return found


def read_truth(folder: str, ids: set[str]) -> dict[str, dict]:
    """The rows of ``ids`` from a folder of page records (local path or fsspec URI; JSON Lines, gzipped or not):
    every file streamed once, only the lines of those ids decoded (the id read from the line's start)."""
    from datatrove.io import get_datafolder

    found: dict[str, dict] = {}
    if not ids:
        return found
    df = get_datafolder(folder)
    for name in sorted(df.list_files(glob_pattern="**/*.jsonl*")):
        with df.open(name, "rt", compression="gzip" if name.endswith(".gz") else None, encoding="utf-8") as fh:
            for line in fh:
                m = _ID.search(line, 0, 400)
                if m is None or json.loads(f'"{m.group(1)}"') not in ids:
                    continue
                row = upgrade(json.loads(line))
                found.setdefault(row["id"], row)
        if len(found) == len(ids):
            break
    return found


def aggregate(scores: str, truth: str, benchmark: Benchmark, transcription: str = "ocr_new",
              policy: RenderingPolicy = DEFAULT_POLICY, run_id: str | None = None) -> dict[str, Any]:
    """The run's result from the score files ``pipelines/score.py``'s tasks wrote (``scores/records/*.jsonl.gz``
    and ``scores/pages/*.jsonl.gz``, local or fsspec): every page of the benchmark the run lacks scored as an empty
    output, then ``summarize``."""
    from datatrove.io import get_datafolder

    df = get_datafolder(scores)

    def rows(sub: str) -> list[dict]:
        got = []
        for name in sorted(df.list_files(subdirectory=sub, glob_pattern="*.jsonl*")):
            with df.open(name, "rt", compression="gzip" if name.endswith(".gz") else None, encoding="utf-8") as fh:
                got += [json.loads(line) for line in fh if line.strip()]
        return got

    records, pages = rows("records"), rows("pages")
    wanted = wanted_pages(benchmark, truth if benchmark.pages.ids is None and benchmark.pages.rule else None)
    want = set(wanted)
    seen = {p["page_id"] for p in pages}
    records = [r for r in records if r["page_id"] in want]
    pages = [p for p in pages if p["page_id"] in want]
    lacking = [pid for pid in wanted if pid not in seen]
    truths = read_truth(truth, set(lacking))
    for pid in lacking:
        if pid not in truths:
            raise ValueError(f"page {pid} of the page set is not in the ground truth")
        recs, summary = score_pair(pid, truths[pid], None, benchmark, transcription, policy, run_id)
        records += recs
        pages.append(summary)
    order = {pid: k for k, pid in enumerate(wanted)}
    pages.sort(key=lambda p: order[p["page_id"]])
    records.sort(key=lambda r: order[r["page_id"]])
    return summarize(records, pages, benchmark)


def write_scores(records: list[dict], path: str | Path) -> Path:
    """The score records as Parquet (zstd), the file's metadata naming the linecaster that wrote it; element rows
    (``score_elements``) in ``elements.parquet`` beside it, a table of their own (their fields are not a page row's)."""
    page_rows = [r for r in records if r.get("level") != "element"]
    element_rows = [r for r in records if r.get("level") == "element"]
    _write_parquet(page_rows, path)
    if element_rows:
        text = str(path)
        sibling = text[:text.rstrip("/").rfind("/") + 1] + "elements.parquet" if "/" in text else "elements.parquet"
        _write_parquet(element_rows, sibling)
    return path


def _write_parquet(rows: list[dict], path: str | Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    from linecaster.data.transcription import producer

    table = pa.Table.from_pylist(rows)
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), b"linecaster": producer().encode()})
    if "://" in str(path):                                  # object storage: through fsspec
        import fsspec

        with fsspec.open(str(path), "wb") as fh:
            pq.write_table(table, fh, compression="zstd")
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")
