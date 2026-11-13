"""An evidence record (``linecaster.evidence/2``) from a scored run: the subject (the run's recipe edition, or the
preset edition named), the run (from its run record), the benchmark, the scoring, the metrics with their intervals,
the counts and the hardware."""
from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

from .. import __version__
from . import SCORER
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
    folder itself): the run record's recipe edition unless ``preset`` names the preset edition measured; a
    ``linecaster.catalog.schema.Evidence2``."""
    from ..catalog.schema import Evidence2

    record, record_sha = _run_record(run)
    recipe = (record.get("recipe") or {}).get("ref") if preset is None else None
    if preset is None and recipe is None:
        raise ValueError("the run names no recipe edition: name the preset edition measured (--preset id@edition)")
    hw = record.get("hardware") or None
    metrics = {k: {key: v.get(key) for key in ("value", "lo", "hi", "n") if key in v}
               for k, v in result["rates"].items()}
    for role, r in (result.get("roles") or {}).items():
        for key in ("precision", "recall"):
            metrics[f"role_{key}_{role}"] = {"value": r[key], "n": result["pages_scored"]}
    software = {k: v for k, v in (record.get("software") or {}).get("packages", {}).items()
                if k in ("vllm", "sglang", "linecaster-kraken", "linecaster-paddlex", "torch")}
    return Evidence2.model_validate({
        "schema": "linecaster.evidence/2", "preset": preset, "recipe": recipe, "context": context,
        "source": "own-run",
        "run": {"uri": str(run), "run_id": record.get("run_id"), "pipeline_sha256": record.get("pipeline_sha256"),
                "record_sha256": record_sha},
        "benchmark": {"ref": benchmark.ref, "sha256": benchmark.sha256},
        "scoring": {"policy": benchmark.policy, "lanes": list(benchmark.lanes), "scorer": SCORER,
                    "linecaster": __version__},
        "metrics": metrics,
        "counts": {k: int(result[k]) for k in ("pages_scored", "missing", "failed")},
        "date": date or dt.date.today(), "hardware": hw, "software": software, "notes": notes})


def write_evidence(ev, path: str | Path) -> Path:
    """The record (an ``Evidence2``) as YAML, its first line naming its schema (as every linecaster YAML file)."""
    from ..catalog import yamlio

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = ev.model_dump(mode="json", by_alias=True, exclude_none=True)
    path.write_text("# yaml-language-server: $schema=https://github.com/storytracer/linecaster/raw/main/src/linecaster/"
                    "catalog/schemas/evidence-2.json\n" + yamlio.dump(data), encoding="utf-8")
    return path
