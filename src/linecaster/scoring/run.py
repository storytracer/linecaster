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

from ..data.page import Page
from ..data.policy import DEFAULT_POLICY, RenderingPolicy
from ..data.sample import listing_sha256
from ..data.upgrade import upgrade
from .aggregate import rates, role_rates
from .benchmark import Benchmark
from .metrics import score_page
from .slices import SLICES

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
    from . import scorer as named

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
                     unit=benchmark.unit, strategy=benchmark.output)
    item_id = truth_page.item_id
    records = [{"schema": SCORE_SCHEMA, "page_id": pid, "item_id": item_id, **r, **flags, "run_id": run_id,
                "benchmark": benchmark.ref, "benchmark_sha256": benchmark.sha256, "policy": policy.ref,
                "output": benchmark.output, "scorer": scorer()} for r in got["rows"]]
    from .render import text as render_text
    from .slices import page_slices

    summary = {"page_id": pid, "item_id": item_id, "roles": got["roles"] if roles else {},
               "confusion": got.get("confusion", []), "missing": out_row is None,
               "failed": flags["error"] is not None, "slices": page_slices(gt, render_text(gt, "full", policy))}
    return records, summary


def summarize(records: list[dict], pages: list[dict], benchmark: Benchmark, warn: bool = True) -> dict[str, Any]:
    """The run's result from its pages' score records and summaries (``score_pair``'s, every page of the benchmark
    once): ``rates`` (metric name -> value, interval, ``n``), ``roles`` (per role precision and recall), the counts
    ``pages_scored``, ``missing``, ``failed`` and ``eligible``, ``conventions`` (lane -> the ground truth's
    declared normalizations it does not apply, on any page: the conventions check; each one warned of), and
    ``slices`` (``linecaster.scoring.slices``: per slice its definition, pages and the rates on its pages; empty for
    page summaries written before 0.10.4, which name no slices)."""
    b = benchmark.bootstrap
    by: dict[tuple[str, str], list[dict]] = {}
    for r in records:
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
    roles = bool(benchmark.supports.roles) and "role_words" in benchmark.metrics
    missing = sum(1 for p in pages if p.get("missing"))
    failed = sum(1 for p in pages if p.get("failed"))
    return {"records": records, "pages": pages, "rates": out_rates, "slices": slices, "conventions": conventions,
            "roles": role_rates([p["roles"] for p in pages]) if roles else {},
            "pages_scored": len(pages), "missing": missing, "failed": failed, "eligible": missing == 0}


def wanted_pages(benchmark: Benchmark, truth_ids=None) -> list[str]:
    """The benchmark's page set (its ids, else every ground-truth page), checked against its hash."""
    wanted = benchmark.pages.ids if benchmark.pages.ids is not None else sorted(truth_ids or ())
    if listing_sha256(wanted) != benchmark.pages.sha256:
        raise ValueError(f"the ground truth's pages are not the benchmark's page set ({benchmark.pages.sha256})")
    return wanted


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
    wanted = wanted_pages(benchmark)
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
    """The score records as Parquet (zstd), the file's metadata naming the linecaster that wrote it."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from ..data.transcription import producer

    table = pa.Table.from_pylist(records)
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), b"linecaster": producer().encode()})
    if "://" in str(path):                                  # object storage: through fsspec
        import fsspec

        with fsspec.open(str(path), "wb") as fh:
            pq.write_table(table, fh, compression="zstd")
        return path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")
    return path
