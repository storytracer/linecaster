"""A benchmark's own harness and linecaster: where its code is, and the harness run unchanged as the reference.

OmniDocBench's evaluation scores linecaster runs in linecaster's own process (``linecaster.scoring.omnidocbench``,
the pipeline ``harness.v1``): its code at the pinned commit (``HARNESSES``), fetched once (``source``) and imported.
This module also runs the pinned harness itself, unchanged, in its own environment of its own pins (``environment``)
and one process (``run``, ``linecaster harness``): the reference the in-process scoring is checked against, value for
value, on a sample of pages. Both write the two sides in the harness's formats (``linecaster.formats.omnidocbench``):
the ground truth as its ground-truth pages (``write_shard``: ``truth.json``), the run's pages as its predictions
(``predictions/<page id>.md``; a page the run lacks: an empty prediction).

    linecaster harness omnidocbench OUT --pages RUN/pages --truth TRUTH/pages [--ids IDS]      # the reference

Harnesses (``HARNESSES``): ``omnidocbench``, OmniDocBench's end-to-end evaluation: text edit distance, tables by TEDS,
TEDS-S and edit distance, display formulas by edit distance (CDM with ``--cdm`` in the reference, which needs TeX
Live, ImageMagick and Ghostscript on the machine), reading order. Its text score keeps only letters and digits and
leaves out running heads and feet, page numbers, footnotes and captions: another view than linecaster's literal
lanes, not a replacement. Pages carry linecaster's page slices (``linecaster.scoring.slices``) as the attributes
``tables``, ``table-heavy`` and ``formulas``, by which the harness groups its page results.

Source and environment live in ``LINECASTER_HARNESS_ENVS`` (default ``~/.cache/linecaster/harnesses``), one folder per
harness commit; the environment adds ``pins`` where the harness leaves a package open that has since moved past
what it works with.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
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
#: the name the harness gives its result files (its prediction folder's, ``predictions``, and its match method)
SAVE = "predictions_quick_match"


def envs_root() -> Path:
    return Path(os.environ.get("LINECASTER_HARNESS_ENVS", Path.home() / ".cache/linecaster/harnesses"))


def source(name: str) -> Path:
    """The harness's source at its commit (``envs_root()/<name>-<commit>``), fetched the first time (one fetcher at a
    time): what ``linecaster.scoring.omnidocbench`` imports."""
    h = HARNESSES[name]
    root = envs_root() / f"{name}-{h['commit'][:8]}"
    if (root / ".linecaster-source").exists():
        return root
    root.parent.mkdir(parents=True, exist_ok=True)
    with open(root.parent / f".{root.name}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (root / ".linecaster-source").exists():
            _fetch(name, root)
    return root


def _fetch(name: str, root: Path) -> None:
    """The harness's source at its commit, from GitHub, into ``root``."""
    h = HARNESSES[name]
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
    (root / ".linecaster-source").write_text(json.dumps({"commit": h["commit"]}))


def environment(name: str) -> Path:
    """The harness's folder (its source and ``.venv`` with its own pins and ``PINS``), built by uv the first time:
    the pinned harness run unchanged (``run``, the reference)."""
    h = HARNESSES[name]
    root = source(name)
    if (root / ".linecaster-ready").exists():
        return root
    with open(root.parent / f".{root.name}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (root / ".linecaster-ready").exists():
            uv = shutil.which("uv") or "uv"
            python = root / ".venv/bin/python"
            subprocess.run([uv, "venv", "-q", "--python", h["python"], str(root / ".venv")], check=True)
            subprocess.run([uv, "pip", "install", "-q", "--python", str(python), "-e", str(root), *h["pins"]],
                           check=True)
            (root / ".linecaster-ready").write_text(json.dumps({"commit": h["commit"], "pins": h["pins"]}))
    return root


def _attributes(gt) -> dict[str, str]:
    """A ground-truth page's slices as page attributes (``yes``/``no``), by which the harness groups pages."""
    from .render import text
    from .slices import page_slices

    sl = page_slices(gt, text(gt, "full"))
    return {k: "yes" if k in sl else "no" for k in ("tables", "table-heavy", "formulas")}


def write_shard(folder: str | Path, truth_rows: dict[str, dict], run_rows: dict[str, dict | None],
                transcription: str = "ocr_new", truth_transcription: str = "ground_truth", tables: str = "data") -> dict:
    """A shard: ``truth.json`` (OmniDocBench's ground truth of ``truth_rows``, page records by id) and
    ``predictions/<id>.md`` (each page of ``run_rows``; a page without a row, or with errors, an empty prediction)."""
    from ..data import Page
    from ..data.upgrade import upgrade
    from ..formats.omnidocbench import prediction_markdown, truth_page

    folder = Path(folder)
    (folder / "predictions").mkdir(parents=True, exist_ok=True)
    pages, missing = [], 0
    for pid, row in truth_rows.items():
        gt = Page.model_validate(upgrade(row)["page"]).transcriptions[truth_transcription]
        pages.append(truth_page(pid, gt, attributes=_attributes(gt), tables=tables))
        out_row = run_rows.get(pid)
        t = None
        if out_row is not None and not out_row.get("errors"):
            t = Page.model_validate(upgrade(out_row)["page"]).transcriptions.get(transcription)
        missing += out_row is None
        (folder / "predictions" / f"{pid}.md").write_text(prediction_markdown(t), encoding="utf-8")
    (folder / "truth.json").write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    return {"pages": len(pages), "missing": missing}


def config(folder: Path, cdm: bool = False, workers: int = 1) -> Path:
    """OmniDocBench's end-to-end config for a shard (its quick match, every module, CDM only when asked)."""
    import yaml

    w = max(1, workers)
    cfg = {"end2end_eval": {
        "metrics": {"text_block": {"metric": ["Edit_dist"]},
                    "display_formula": {"metric": ["Edit_dist", *(["CDM"] if cdm else [])], "cdm_workers": w},
                    "table": {"metric": ["TEDS", "Edit_dist"], "teds_workers": w},
                    "reading_order": {"metric": ["Edit_dist"]}},
        "dataset": {"dataset_name": "end2end_dataset", "ground_truth": {"data_path": str(folder / "truth.json")},
                    "prediction": {"data_path": str(folder / "predictions")}, "match_method": "quick_match",
                    "match_workers": w}}}
    path = folder / "end2end.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return path


def run_shard(name: str, folder: str | Path, cdm: bool = False, workers: int = 1) -> None:
    """The harness on one shard, in its folder (its results in ``folder/result``, its log ``folder/harness.log``)."""
    folder = Path(folder).resolve()
    root = environment(name)
    cfg = config(folder, cdm, workers)
    env = {**os.environ, "HF_HOME": os.environ.get("HF_HOME", str(Path.home() / ".cache/huggingface"))}
    with open(folder / "harness.log", "w") as log:
        subprocess.run([str(root / ".venv/bin/python"), str(root / "pdf_validation.py"), "--config", str(cfg)],
                       cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)


def _truth_ids(folder: str) -> set[str]:
    from datatrove.io import get_datafolder

    from .run import _ID

    df = get_datafolder(folder)
    found: set[str] = set()
    for name in df.list_files(glob_pattern="**/*.jsonl*"):
        with df.open(name, "rt", compression="gzip" if name.endswith(".gz") else None, encoding="utf-8") as fh:
            for line in fh:
                m = _ID.search(line, 0, 400)
                if m:
                    found.add(json.loads(f'"{m.group(1)}"'))
    return found


def run(name: str, out: str | Path, pages: str, truth: str, transcription: str = "ocr_new",
        truth_transcription: str = "ground_truth", ids: set[str] | None = None, cdm: bool = False,
        workers: int = 8, tables: str = "data") -> dict:
    """The pinned harness, unchanged, in its own environment and one process, on every page of ``ids`` (default:
    every ground-truth page; a page the run lacks: an empty prediction): ``linecaster harness``, the reference the
    in-process scoring (``linecaster.scoring.omnidocbench``, the pipeline ``harness.v1``) is checked against.
    ``OUT/result/`` holds the harness's results as it writes them, ``OUT/harness.yaml`` what produced them."""
    import datetime as dt

    import yaml

    from . import scorer
    from .run import read_truth

    if name not in HARNESSES:
        raise ValueError(f"unknown harness {name!r}; known: {sorted(HARNESSES)}")
    out = Path(out).resolve()
    wanted = set(ids) if ids is not None else _truth_ids(truth)
    shutil.rmtree(out / "result", ignore_errors=True)
    shutil.rmtree(out / "predictions", ignore_errors=True)
    run_rows = read_truth(pages, wanted)
    counts = write_shard(out, read_truth(truth, wanted), run_rows, transcription, truth_transcription, tables)
    run_shard(name, out, cdm, workers)
    result = json.loads((out / f"result/{SAVE}_metric_result.json").read_text())
    h = HARNESSES[name]
    record = {"schema": "linecaster.harness-run/1", "harness": name, "repo": h["repo"], "commit": h["commit"],
              "pins": h["pins"], "process": "the pinned harness, one process", "cdm": cdm, "pages": str(pages),
              "truth": str(truth), "transcription": transcription, "truth_transcription": truth_transcription,
              "tables": tables, "counts": counts, "metrics": summarize(result), "exporter": scorer(), "date": dt.date.today().isoformat()}
    (out / "harness.yaml").write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True))
    return record


def summarize(result: dict) -> dict:
    """The harness's headline numbers from its metric result, and the same per page group (its page attributes)."""
    def get(*keys):
        d = result
        for k in keys:
            if not isinstance(d, dict) or k not in d:
                return None
            d = d[k]
        return d if isinstance(d, (int, float)) else None

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
        for g, v in ((result.get(module) or {}).get("page", {}).get("Edit_dist") or {}).items():
            if g != "ALL" and isinstance(v, (int, float)):
                groups.setdefault(g, {})[key] = float(v)
    return {**{k: float(v) for k, v in out.items() if v is not None}, "groups": groups}
