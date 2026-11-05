"""``linecaster traces OUT``: what a run's traces say (``OUT/traces/**/*.jsonl.gz``, OTLP JSON lines).

* **blocks**: per block (``--by block``; or per preset edition, or per task) the duration of its ``linecaster.block``
  spans (p50, p90, p99 over the traced pages), for served blocks the split of a request: the whole request as the
  pipeline saw it, and the server's queue, decode and model spans;
* **gaps**: the time each block had no page in it between its first and its last (it waited for its input), when
  every page was traced (``--trace-sample 1``); from a sample they would only show the pages not traced;
* **slowest pages**: the ``N`` traced pages that took longest, with their attributes and slowest block;
* **tasks**: per task its duration, the warm-up of each block, the server starts, the reader's files and the
  writers' flushes.
"""
from __future__ import annotations

import gzip
import io
import json
from collections import defaultdict

BY = ("block", "preset", "task")


def _value(v: dict):
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        return int(v["intValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "boolValue" in v:
        return bool(v["boolValue"])
    if "arrayValue" in v:
        return [_value(x) for x in v["arrayValue"].get("values", [])]
    return None


def _attrs(items) -> dict:
    return {a["key"]: _value(a.get("value") or {}) for a in items or ()}


def read_spans(out: str) -> list[dict]:
    """Every span under ``OUT/traces`` (any fsspec folder): ``{"trace", "span", "parent", "name", "start", "end"
    (seconds since the epoch), "seconds", "attrs", "error", "resource"}``."""
    from datatrove.io import get_datafolder

    folder = get_datafolder(f"{out.rstrip('/')}/traces")
    if not folder.exists(""):
        return []
    spans = []
    for name in sorted(folder.glob("**/*.jsonl.gz")):
        with folder.open(name, "rb") as raw:
            data = raw.read()
        try:
            text = gzip.decompress(data).decode("utf-8")
        except (EOFError, gzip.BadGzipFile):           # a file still being written (a running task): what is there
            text = _partial(data)
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                continue
            for rs in request.get("resourceSpans", []):
                res = _attrs((rs.get("resource") or {}).get("attributes"))
                res["file"] = name
                for ss in rs.get("scopeSpans", []):
                    for s in ss.get("spans", []):
                        start, end = int(s["startTimeUnixNano"]) / 1e9, int(s["endTimeUnixNano"]) / 1e9
                        spans.append({"trace": s["traceId"], "span": s["spanId"], "parent": s.get("parentSpanId"),
                                      "name": s["name"], "start": start, "end": end, "seconds": end - start,
                                      "attrs": _attrs(s.get("attributes")),
                                      "error": (s.get("status") or {}).get("code") == 2, "resource": res})
    return spans


def _partial(data: bytes) -> str:
    out = io.BytesIO()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as f:
            while chunk := f.read(65536):
                out.write(chunk)
    except (EOFError, gzip.BadGzipFile, OSError):
        pass
    return out.getvalue().decode("utf-8", errors="ignore").rsplit("\n", 1)[0]


def percentile(values: list[float], q: float) -> float | None:
    """The nearest-rank percentile ``q`` (0-100) of ``values``."""
    if not values:
        return None
    v = sorted(values)
    k = max(0, min(len(v) - 1, int(-(-q * len(v) // 100)) - 1))
    return v[k]


def _dist(values: list[float]) -> dict:
    return {"n": len(values), "p50": percentile(values, 50), "p90": percentile(values, 90),
            "p99": percentile(values, 99), "total": sum(values)}


def _task_key(res: dict) -> str:
    stage = res.get("linecaster.stage")
    task = res.get("linecaster.task")
    return (f"{stage}/" if stage else "") + (f"task {task}" if task is not None else res.get("file", "?"))


def _group(s: dict, by: str) -> str:
    a = s["attrs"]
    if by == "preset":
        p = a.get("linecaster.preset")
        return f"{p}@{a['linecaster.edition']}" if p and a.get("linecaster.edition") else (p or "(no preset)")
    if by == "task":
        return _task_key(s["resource"])
    return a.get("linecaster.block.name") or a.get("linecaster.block") or "?"


def _idle(intervals: list[tuple[float, float]]) -> tuple[float, float]:
    """(seconds with no interval open between the first start and the last end, that whole span)."""
    if not intervals:
        return 0.0, 0.0
    intervals.sort()
    busy, (cs, ce) = 0.0, intervals[0]
    for s, e in intervals[1:]:
        if s > ce:
            busy += ce - cs
            cs, ce = s, e
        else:
            ce = max(ce, e)
    busy += ce - cs
    whole = max(e for _, e in intervals) - intervals[0][0]
    return max(0.0, whole - busy), whole


def summarize(spans: list[dict], by: str = "block", slowest: int = 10) -> dict:
    """The report as data (``--json``)."""
    children = defaultdict(list)
    for s in spans:
        if s["parent"]:
            children[(s["trace"], s["parent"])].append(s)
    tasks = [s for s in spans if s["name"] == "linecaster.task"]
    roots = [s for s in spans if s["name"] in ("linecaster.page", "linecaster.item") and not s["parent"]]
    blocks = [s for s in spans if s["name"] == "linecaster.block"]
    fully = bool(tasks) and all(t["attrs"].get("linecaster.sample") == 1 for t in tasks)

    groups: dict[str, dict] = {}
    for s in blocks:
        g = groups.setdefault(_group(s, by), {"seconds": [], "request": [], "prepare": [], "queue": [],
                                             "decode": [], "model": [], "errors": 0, "intervals": defaultdict(list)})
        g["seconds"].append(s["seconds"])
        g["errors"] += s["error"]
        g["intervals"][_task_key(s["resource"])].append((s["start"], s["end"]))
        for c in children[(s["trace"], s["span"])]:
            if c["name"] == "linecaster.request.prepare":
                g["prepare"].append(c["seconds"])
            elif c["name"] == "linecaster.request":
                g["request"].append(c["seconds"])
                for sc in children[(c["trace"], c["span"])]:
                    kind = sc["name"].rsplit(".", 1)[-1]
                    if sc["name"].startswith("linecaster.serve.") and kind in ("queue", "decode", "model"):
                        g[kind].append(sc["seconds"])
    block_rows = {}
    for name, g in groups.items():
        row = {"seconds": _dist(g["seconds"]), "errors": g["errors"]}
        if g["request"]:
            row["served"] = {k: _dist(g[k]) for k in ("prepare", "request", "queue", "decode", "model") if g[k]}
        if fully:
            idle = whole = 0.0
            for intervals in g["intervals"].values():
                i, w = _idle(intervals)
                idle, whole = idle + i, whole + w
            row["gaps"] = {"idle_seconds": idle, "active_window_seconds": whole,
                           "idle_share": idle / whole if whole else 0.0}
        block_rows[name] = row

    def page_row(r: dict) -> dict:
        kids = [c for c in children[(r["trace"], r["span"])] if c["name"] == "linecaster.block"]
        worst = max(kids, key=lambda c: c["seconds"], default=None)
        lines = max((c["attrs"].get("linecaster.lines", 0) for c in kids), default=None)
        return {"id": r["attrs"].get("linecaster.page.id") or r["attrs"].get("linecaster.item.id"),
                "item": r["attrs"].get("linecaster.item.id") if r["attrs"].get("linecaster.page.id") else None,
                "trace_id": r["trace"], "seconds": r["seconds"], "failed": r["error"],
                "unfinished": bool(r["attrs"].get("linecaster.unfinished")), "lines": lines,
                "slowest_block": ({"block": worst["attrs"].get("linecaster.block.name")
                                   or worst["attrs"].get("linecaster.block"), "seconds": worst["seconds"]}
                                  if worst else None), "task": _task_key(r["resource"])}

    task_rows = {}
    for t in sorted(tasks, key=lambda t: _task_key(t["resource"])):
        kids = children[(t["trace"], t["span"])]
        files = [c for c in kids if c["name"] == "linecaster.reader.file"]
        flushes = [c for c in kids if c["name"] == "linecaster.writer.flush"]
        task_rows[_task_key(t["resource"])] = {
            "seconds": t["seconds"], "failed": t["error"], "gpu": t["resource"].get("linecaster.gpu"),
            "sample": t["attrs"].get("linecaster.sample"),
            "warm_up": [{"span": c["name"], "block": c["attrs"].get("linecaster.block.name")
                         or c["attrs"].get("linecaster.block"), "seconds": c["seconds"]}
                        for c in sorted(kids, key=lambda c: c["start"])
                        if c["name"] in ("linecaster.warm_up", "linecaster.server.start")],
            "reader_files": {"n": len(files), "pages": sum(c["attrs"].get("linecaster.pages", 0) for c in files),
                             "seconds_own": sum(c["attrs"].get("linecaster.seconds.own", 0.0) for c in files)},
            "writer_flush_seconds": sum(c["seconds"] for c in flushes)}
    return {"spans": len(spans), "tasks": len(tasks),
            "units": {"traced": len(roots), "failed": sum(r["error"] for r in roots)},
            "by": by, "blocks": block_rows, "gaps_available": fully,
            "slowest": [page_row(r) for r in sorted(roots, key=lambda r: -r["seconds"])[:slowest]],
            "per_task": task_rows}


def _f(v) -> str:
    return "-" if v is None else (f"{v:.3f}" if v < 10 else f"{v:.1f}")


def render(report: dict) -> str:
    """The report as plain text."""
    out = [f"{report['spans']} spans, {report['tasks']} tasks, {report['units']['traced']} traced units "
           f"({report['units']['failed']} failed)", ""]
    if report["blocks"]:
        width = max(12, *(len(k) for k in report["blocks"]))
        out.append(f"{report['by']:<{width}}  {'n':>6}  {'p50 s':>8}  {'p90 s':>8}  {'p99 s':>8}  errors")
        for name, row in report["blocks"].items():
            d = row["seconds"]
            out.append(f"{name:<{width}}  {d['n']:>6}  {_f(d['p50']):>8}  {_f(d['p90']):>8}  {_f(d['p99']):>8}  "
                       f"{row['errors']}")
            for part, dd in (row.get("served") or {}).items():
                out.append(f"{'  ' + part:<{width}}  {dd['n']:>6}  {_f(dd['p50']):>8}  {_f(dd['p90']):>8}  "
                           f"{_f(dd['p99']):>8}")
        out.append("")
        if report["gaps_available"]:
            out.append("gaps (time a block had no page, between its first and its last)")
            for name, row in report["blocks"].items():
                g = row.get("gaps")
                if g:
                    out.append(f"  {name:<{width}}  {_f(g['idle_seconds'])} s of {_f(g['active_window_seconds'])} s "
                               f"({100 * g['idle_share']:.0f} %)")
        else:
            out.append("gaps: only with every page traced (--trace-sample 1)")
        out.append("")
    if report["slowest"]:
        out.append("slowest units")
        for p in report["slowest"]:
            worst = p["slowest_block"]
            flags = (" failed" if p["failed"] else "") + (" unfinished" if p["unfinished"] else "")
            out.append(f"  {p['id']}  {_f(p['seconds'])} s  lines={p['lines'] if p['lines'] is not None else '-'}  "
                       f"slowest: {worst['block'] + ' ' + _f(worst['seconds']) + ' s' if worst else '-'}  "
                       f"trace {p['trace_id']}{flags}")
        out.append("")
    for key, t in report["per_task"].items():
        gpu = f", {t['gpu']}" if t.get("gpu") else ""
        out.append(f"{key}: {_f(t['seconds'])} s{' (failed)' if t['failed'] else ''}{gpu}, sample {t['sample']}")
        for w in t["warm_up"]:
            what = "server start" if w["span"] == "linecaster.server.start" else "warm-up"
            out.append(f"  {what:<12}  {w['block']}: {_f(w['seconds'])} s")
        rf = t["reader_files"]
        if rf["n"]:
            out.append(f"  reader        {rf['n']} files, {rf['pages']} pages, {_f(rf['seconds_own'])} s reading")
        if t["writer_flush_seconds"]:
            out.append(f"  writer flush  {_f(t['writer_flush_seconds'])} s")
    return "\n".join(out).rstrip() + "\n"
