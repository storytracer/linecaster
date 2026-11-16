"""A benchmark's own harness scoring a linecaster run against a linecaster ground truth: the ground truth written in
the harness's ground-truth format, the run's pages as its predictions, the harness run unchanged at a pinned commit
in its own environment, and its results kept with what produced them (``harness.yaml``).

    linecaster harness omnidocbench OUT --pages RUN/pages --truth TRUTH/pages [--ids IDS] [--cdm] [--workers N]

Harnesses (``HARNESSES``): ``omnidocbench``, OmniDocBench's end-to-end evaluation (``linecaster.formats.omnidocbench``
writes its formats): text edit distance, tables by TEDS, TEDS-S and edit distance, display formulas by edit distance
(and CDM with ``--cdm``, which needs TeX Live, ImageMagick and Ghostscript on the machine), reading order. Its text
score keeps only letters and digits and leaves out running heads and feet, page numbers, footnotes and captions:
another view than linecaster's literal lanes, not a replacement. Its results are grouped by page attributes:
linecaster's page slices (``linecaster.scoring.slices``) as ``tables`` and ``formulas``.

The environment is built once per harness commit by uv (``LINECASTER_HARNESS_ENVS``, default
``~/.cache/linecaster/harnesses``): the harness's source at the commit, a virtual environment of its Python, the
harness installed with its own pins, plus ``PINS`` where it leaves a package open that has since moved past what it
works with.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from loguru import logger

#: harness -> its source, the commit linecaster runs, its Python, and pins it leaves open
HARNESSES: dict[str, dict[str, Any]] = {
    "omnidocbench": {
        "repo": "opendatalab/OmniDocBench", "commit": "7ddb8df411ad9bd2fff139acafe0ed16aa1694fe", "python": "3.11",
        # evaluate 0.4.3 imports datasets, whose newest pyarrow needs NumPy 2; the harness pins NumPy 1.24.4
        "pins": ["datasets==3.0.1", "pyarrow==17.0.0"],
    },
}


def envs_root() -> Path:
    return Path(os.environ.get("LINECASTER_HARNESS_ENVS", Path.home() / ".cache/linecaster/harnesses"))


def environment(name: str) -> Path:
    """The harness's folder (its source and ``.venv``), built by uv the first time."""
    h = HARNESSES[name]
    root = envs_root() / f"{name}-{h['commit'][:8]}"
    python = root / ".venv/bin/python"
    if python.exists() and (root / ".linecaster-ready").exists():
        return root
    root.parent.mkdir(parents=True, exist_ok=True)
    tmp = root.with_name(root.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    url = f"https://github.com/{h['repo']}/archive/{h['commit']}.tar.gz"
    logger.info("harness {}: fetching {}", name, url)
    with urllib.request.urlopen(url) as r, tarfile.open(fileobj=r, mode="r|gz") as tar:
        tar.extractall(tmp, filter="data")
    (src,) = list(tmp.iterdir())
    shutil.rmtree(root, ignore_errors=True)
    src.rename(root)
    shutil.rmtree(tmp, ignore_errors=True)
    uv = shutil.which("uv") or "uv"
    subprocess.run([uv, "venv", "-q", "--python", h["python"], str(root / ".venv")], check=True)
    subprocess.run([uv, "pip", "install", "-q", "--python", str(python), "-e", str(root), *h["pins"]], check=True)
    (root / ".linecaster-ready").write_text(json.dumps({"commit": h["commit"], "pins": h["pins"]}))
    return root


def _records(folder: str) -> list[str]:
    from datatrove.io import get_datafolder

    df = get_datafolder(folder)
    return [df.resolve_paths(n) for n in sorted(df.list_files(glob_pattern="**/*.jsonl*"))]


def _rows(path: str):
    from datatrove.io import open_file

    with open_file(path, "rt", compression="gzip" if path.endswith(".gz") else None) as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def _export_truth(args) -> list[dict]:
    path, transcription, ids = args
    from ..data import Page
    from ..data.upgrade import upgrade
    from ..formats.omnidocbench import truth_page
    from .render import text
    from .slices import page_slices

    out = []
    for row in _rows(path):
        if ids is not None and row["id"] not in ids:
            continue
        page = Page.model_validate(upgrade(row)["page"])
        gt = page.transcriptions[transcription]
        sl = page_slices(gt, text(gt, "full"))
        attrs = {"tables": "yes" if "tables" in sl else "no", "formulas": "yes" if "formulas" in sl else "no",
                 "table-heavy": "yes" if "table-heavy" in sl else "no"}
        out.append(truth_page(row["id"], gt, attributes=attrs))
    return out


def _export_predictions(args) -> list[str]:
    path, transcription, ids, folder = args
    from ..data import Page
    from ..data.upgrade import upgrade
    from ..formats.omnidocbench import prediction_markdown

    done = []
    for row in _rows(path):
        if ids is not None and row["id"] not in ids:
            continue
        page = Page.model_validate(upgrade(row)["page"])
        t = None if row.get("errors") else page.transcriptions.get(transcription)
        (Path(folder) / f"{row['id']}.md").write_text(prediction_markdown(t), encoding="utf-8")
        done.append(row["id"])
    return done


def export(out: str | Path, pages: str, truth: str, transcription: str = "ocr_new",
           truth_transcription: str = "ground_truth", ids: set[str] | None = None, workers: int = 8) -> dict:
    """The ground truth as ``OUT/truth.json`` and the run's pages as ``OUT/predictions/<page id>.md`` (a page the run
    lacks: an empty file, as the harness scores a missing prediction)."""
    out = Path(out)
    (out / "predictions").mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(workers) as ex:
        truth_pages = [p for part in ex.map(_export_truth, [(f, truth_transcription, ids) for f in _records(truth)])
                       for p in part]
        folder = str(out / "predictions")
        written = {i for part in ex.map(_export_predictions, [(f, transcription, ids, folder) for f in _records(pages)])
                   for i in part}
    missing = [p["page_info"]["image_path"].removesuffix(".png") for p in truth_pages
               if p["page_info"]["image_path"].removesuffix(".png") not in written]
    for pid in missing:
        (out / "predictions" / f"{pid}.md").write_text("", encoding="utf-8")
    (out / "truth.json").write_text(json.dumps(truth_pages, ensure_ascii=False), encoding="utf-8")
    logger.info("harness export: {} ground-truth pages, {} predictions, {} missing", len(truth_pages), len(written),
                len(missing))
    return {"pages": len(truth_pages), "predictions": len(written), "missing": len(missing)}


def config(out: Path, cdm: bool, workers: int) -> Path:
    """OmniDocBench's end-to-end config for ``out`` (its quick match, every module, CDM only when asked)."""
    import yaml

    w = max(1, workers)
    cfg = {"end2end_eval": {
        "metrics": {"text_block": {"metric": ["Edit_dist"]},
                    "display_formula": {"metric": ["Edit_dist", *(["CDM"] if cdm else [])], "cdm_workers": w},
                    "table": {"metric": ["TEDS", "Edit_dist"], "teds_workers": w},
                    "reading_order": {"metric": ["Edit_dist"]}},
        "dataset": {"dataset_name": "end2end_dataset", "ground_truth": {"data_path": str(out / "truth.json")},
                    "prediction": {"data_path": str(out / "predictions")}, "match_method": "quick_match",
                    "match_workers": w}}}
    path = out / "end2end.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return path


def run(name: str, out: str | Path, pages: str, truth: str, transcription: str = "ocr_new",
        truth_transcription: str = "ground_truth", ids: set[str] | None = None, cdm: bool = False,
        workers: int = 8) -> dict:
    """The harness ``name`` on the run's ``pages`` against ``truth``, in ``out``: its results in ``out/result``, and
    ``out/harness.yaml`` naming the harness, its commit and pins, the inputs and the summary metrics."""
    import datetime as dt

    import yaml

    from . import scorer

    if name not in HARNESSES:
        raise ValueError(f"unknown harness {name!r}; known: {sorted(HARNESSES)}")
    out = Path(out).resolve()
    root = environment(name)
    counts = export(out, pages, truth, transcription, truth_transcription, ids, workers)
    cfg = config(out, cdm, workers)
    env = {**os.environ, "HF_HOME": os.environ.get("HF_HOME", str(Path.home() / ".cache/huggingface"))}
    logger.info("harness {}: running on {} pages", name, counts["pages"])
    with open(out / "harness.log", "w") as log:
        subprocess.run([str(root / ".venv/bin/python"), str(root / "pdf_validation.py"), "--config", str(cfg)],
                       cwd=out, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    result = json.loads((out / "result/predictions_quick_match_metric_result.json").read_text())   # named by the folder
    summary = summarize(result)
    h = HARNESSES[name]
    record = {"schema": "linecaster.harness-run/1", "harness": name, "repo": h["repo"], "commit": h["commit"],
              "pins": h["pins"], "cdm": cdm, "pages": str(pages), "truth": str(truth),
              "transcription": transcription, "truth_transcription": truth_transcription, "counts": counts,
              "metrics": summary, "exporter": scorer(), "date": dt.date.today().isoformat()}
    (out / "harness.yaml").write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True))
    return record


def summarize(result: dict) -> dict:
    """The harness's headline numbers from its metric result (``*_metric_result.json``), and the same per page group
    (its page attributes)."""
    def get(*keys):
        d = result
        for k in keys:
            if not isinstance(d, dict) or k not in d:
                return None
            d = d[k]
        return d

    out = {
        "text_edit": get("text_block", "all", "Edit_dist", "ALL_page_avg"),
        "table_teds": get("table", "all", "TEDS", "all"),
        "table_teds_s": get("table", "all", "TEDS_structure_only", "all"),
        "table_edit": get("table", "all", "Edit_dist", "ALL_page_avg"),
        "formula_edit": get("display_formula", "all", "Edit_dist", "ALL_page_avg"),
        "formula_cdm": get("display_formula", "all", "CDM", "all"),
        "reading_order_edit": get("reading_order", "all", "Edit_dist", "ALL_page_avg"),
    }
    groups: dict[str, dict] = {}
    for module, key in (("text_block", "text_edit"), ("display_formula", "formula_edit"), ("table", "table_edit"),
                        ("reading_order", "reading_order_edit")):
        for g, v in (get(module, "page", "Edit_dist") or {}).items():
            if g != "ALL" and isinstance(v, (int, float)):
                groups.setdefault(g, {})[key] = v
    return {**{k: v for k, v in out.items() if v is not None}, "groups": groups}
