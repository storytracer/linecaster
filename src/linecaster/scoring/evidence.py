"""An evidence record (``linecaster.evidence/3``) from a scored run: the subject (the run's recipe, or the preset
named) with its hash, the run (from its run record), the benchmark, the scoring (policy, output strategy, lanes, each
with its hash; the unit; the scorer), the metrics with their intervals, the counts and the hardware."""
from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

from . import scorer
from .benchmark import Benchmark


def _run_record(run: str | Path) -> tuple[dict[str, Any], str | None]:
    from ..catalog import yamlio

    for path in (Path(run) / "run.yaml", Path(run).parent / "run.yaml"):
        if path.is_file():
            return yamlio.load(path.read_text(encoding="utf-8")) or {}, "sha256:" + hashlib.sha256(
                path.read_bytes()).hexdigest()
    return {}, None


def evidence(result: dict[str, Any], benchmark: Benchmark, run: str | Path, preset: str | None = None,
             context: str | None = None, notes: str | None = None, date: dt.date | None = None):
    """The evidence record of ``result`` (``score_run``'s) for the run folder ``run`` (its ``pages/`` or the
    folder itself): the run record's recipe unless ``preset`` names the preset measured; a
    ``linecaster.catalog.schema.Evidence3``."""
    from ..catalog.registry import catalog, canonical_sha256, entry_id
    from ..catalog.schema import Evidence3
    from .lanes import resolve

    record, record_sha = _run_record(run)
    recipe = (record.get("recipe") or {}) if preset is None else {}
    if preset is None and not recipe.get("ref"):
        raise ValueError("the run names no recipe: name the preset measured (--preset id)")
    subject_sha = recipe.get("sha256") if recipe else next(
        (e["sha256"] for e in record.get("catalog") or [] if e["kind"] == "preset" and e["id"] == entry_id(preset)),
        None)
    c = catalog()
    policy_sha = canonical_sha256(c.policy_functional(c.policies[entry_id(benchmark.policy)][1]))
    hw = record.get("hardware") or None
    metrics = {k: {key: v.get(key) for key in ("value", "lo", "hi", "n") if key in v}
               for k, v in result["rates"].items()}
    for role, r in (result.get("roles") or {}).items():
        for key in ("precision", "recall"):
            metrics[f"role_{key}_{role}"] = {"value": r[key], "n": result["pages_scored"]}
    software = {k: v for k, v in (record.get("software") or {}).get("packages", {}).items()
                if k in ("vllm", "sglang", "linecaster-kraken", "linecaster-paddlex", "torch")}
    return Evidence3.model_validate({
        "schema": "linecaster.evidence/3", "preset": entry_id(preset) if preset else None,
        "recipe": recipe.get("ref") if recipe else None, "sha256": subject_sha, "context": context,
        "source": "own-run",
        "run": {"uri": str(run), "run_id": record.get("run_id"), "pipeline_sha256": record.get("pipeline_sha256"),
                "record_sha256": record_sha},
        "benchmark": {"ref": benchmark.ref, "sha256": benchmark.sha256},
        "scoring": {"policy": {"id": entry_id(benchmark.policy), "sha256": policy_sha},
                    "output": {"id": benchmark.output, "sha256": c.strategy(benchmark.output, use="output").sha256},
                    "lanes": [{"id": ln, "sha256": resolve(ln).sha256} for ln in benchmark.lanes],
                    "unit": benchmark.unit, "scorer": scorer()},
        "metrics": metrics,
        "counts": {k: int(result[k]) for k in ("pages_scored", "missing", "failed")},
        "date": date or dt.date.today(), "hardware": hw, "software": software, "notes": notes})


def write_evidence(ev, path: str | Path) -> Path:
    """The record (an ``Evidence3``) as YAML, its first line naming its schema (as every linecaster YAML file)."""
    from ..catalog import yamlio

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = ev.model_dump(mode="json", by_alias=True, exclude_none=True)
    path.write_text("# yaml-language-server: $schema=https://github.com/storytracer/linecaster/raw/main/src/linecaster/"
                    "catalog/schemas/evidence-3.json\n" + yamlio.dump(data), encoding="utf-8")
    return path
