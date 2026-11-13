"""Scoring a run: its page records against a ground truth's, by a benchmark, into score records and corpus rates.

``score_run(run, truth, benchmark)`` reads both folders of page records (JSON Lines, gzipped or not, or Parquet, as
linecaster's page writers write them; older formats upgraded), pairs the pages of the benchmark's page set by page
id, and scores each. A page the run lacks or failed counts as an empty output and is counted (``missing``,
``failed``); a run that lacks pages is not eligible.
"""
from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..data.page import Page
from ..data.policy import DEFAULT_POLICY, RenderingPolicy
from ..data.sample import listing_sha256
from ..data.upgrade import page_2_to_3
from .aggregate import rates, role_rates
from .benchmark import Benchmark
from .metrics import score_page

SCORE_SCHEMA = "linecaster.score/1"


def read_records(folder: str | Path) -> Iterator[dict]:
    """The stored rows (``{"schema", "id", "text", "page", "errors"?}``) of a folder of page records, upgraded."""
    folder = Path(folder)
    for f in sorted(p for p in folder.rglob("*") if p.is_file()):
        if f.name.endswith((".jsonl", ".jsonl.gz")):
            opener = gzip.open if f.name.endswith(".gz") else open
            with opener(f, "rt", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        yield page_2_to_3(json.loads(line))
        elif f.suffix == ".parquet":
            import pyarrow.parquet as pq

            for row in pq.read_table(f).to_pylist():
                for key in ("page", "errors"):
                    if isinstance(row.get(key), str):
                        row[key] = json.loads(row[key])
                yield page_2_to_3(row)


def score_run(run: str | Path, truth: str | Path, benchmark: Benchmark, transcription: str = "ocr_new",
              policy: RenderingPolicy = DEFAULT_POLICY, run_id: str | None = None) -> dict[str, Any]:
    """Scores the run's page records against the ground truth's. Returns ``records`` (score records), ``pages``
    (per page: ``page_id``, ``item_id``, ``roles``, ``confusion``), ``rates`` (metric name -> value, interval,
    ``n``), ``roles`` (per role precision and recall), and the counts ``pages_scored``, ``missing``, ``failed`` and
    ``eligible``."""
    if policy.ref != benchmark.policy:
        raise ValueError(f"the benchmark renders with {benchmark.policy}, not {policy.ref}")
    truths = {r["id"]: r for r in read_records(truth)}
    wanted = benchmark.pages.ids if benchmark.pages.ids is not None else sorted(truths)
    if listing_sha256(wanted) != benchmark.pages.sha256:
        raise ValueError(f"the ground truth's pages are not the benchmark's page set ({benchmark.pages.sha256})")
    outputs = {r["id"]: r for r in read_records(run) if r["id"] in set(wanted)}
    roles = bool(benchmark.supports.roles) and "role_words" in benchmark.metrics
    boxes = "confusion" in benchmark.metrics
    records, pages, missing, failed = [], [], 0, 0
    for pid in wanted:
        tr = truths.get(pid)
        if tr is None:
            raise ValueError(f"page {pid} of the page set is not in the ground truth")
        truth_page = Page.model_validate(tr["page"])
        gt = truth_page.transcriptions[benchmark.dataset.transcription]
        row = outputs.get(pid)
        out = None
        flags = {"missing": row is None, "error": None, "finish_reason": None}
        if row is None:
            missing += 1
        else:
            page = Page.model_validate(row["page"])
            out = page.transcriptions.get(transcription)
            if row.get("errors"):
                failed += 1
                flags["error"] = "; ".join(str(e.get("error", e)) for e in row["errors"]) if isinstance(
                    row["errors"], list) else str(row["errors"])
                out = None
            elif out is not None and out.annotators:
                flags["finish_reason"] = next((a.measurements.get("finish_reason") for a in reversed(out.annotators)
                                               if "finish_reason" in a.measurements), None)
        got = score_page(gt, out, benchmark.texts, benchmark.lanes, policy, boxes=boxes)
        item_id = truth_page.item_id
        for r in got["rows"]:
            records.append({"schema": SCORE_SCHEMA, "page_id": pid, "item_id": item_id, **r, **flags,
                            "run_id": run_id, "benchmark": benchmark.ref, "benchmark_sha256": benchmark.sha256,
                            "policy": policy.ref})
        pages.append({"page_id": pid, "item_id": item_id, "roles": got["roles"] if roles else {},
                      "confusion": got.get("confusion", [])})
    b = benchmark.bootstrap
    out_rates: dict[str, Any] = {}
    for name in benchmark.texts:
        for ln in benchmark.lanes:
            sel = [r for r in records if r["text"] == name and r["lane"] == ln]
            for metric in ("cer", "token_recall", "over_extraction"):
                if metric in benchmark.metrics:
                    key = f"{metric}_{name}_{ln.split('@')[0]}"
                    out_rates[key] = rates(sel, metric, b.seed, b.resamples, b.level)
    return {"records": records, "pages": pages, "rates": out_rates,
            "roles": role_rates([p["roles"] for p in pages]) if roles else {},
            "pages_scored": len(wanted), "missing": missing, "failed": failed, "eligible": missing == 0}


def write_scores(records: list[dict], path: str | Path) -> Path:
    """The score records as Parquet (zstd)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(records), path, compression="zstd")
    return path
