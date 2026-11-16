"""A benchmark's own harness scoring a linecaster run against a linecaster ground truth: the ground truth written in
the harness's ground-truth format, the run's pages as its predictions, the harness run unchanged at a pinned commit
in its own environment, and its results kept with what produced them (``harness.yaml``).

    uv run pipelines/harness.py OUT --pages RUN/pages --truth TRUTH/pages --harness omnidocbench --tasks 100
    linecaster harness omnidocbench OUT --pages RUN/pages --truth TRUTH/pages        # one process, small sets

The harness's work is sharded (``harness.v1``): each task writes its pages as a shard (``OUT/shards/<task>``: its
ground truth and predictions) and runs the harness on it in one process; when every task is done, the pages of the
ground truth no task had (the run lacks them) are a shard of empty predictions, and the shards' per-sample results
are put together by the harness's own aggregation (``merge``; for OmniDocBench
``linecaster.scoring.harness_merge_omnidocbench``), as one run on all pages would have. (OmniDocBench's own workers
are threads, so one process uses about one core whatever its worker count.)

Harnesses (``HARNESSES``): ``omnidocbench``, OmniDocBench's end-to-end evaluation (``linecaster.formats.omnidocbench``
writes its formats): text edit distance, tables by TEDS, TEDS-S and edit distance, display formulas by edit distance,
reading order. Its text score keeps only letters and digits and leaves out running heads and feet, page numbers,
footnotes and captions: another view than linecaster's literal lanes, not a replacement. Its results are grouped by
page attributes: linecaster's page slices (``linecaster.scoring.slices``) as ``tables``, ``table-heavy`` and
``formulas``. CDM (``--cdm``: TeX Live, ImageMagick and Ghostscript on the machine) runs only unsharded, in one shard.

The environment is built once per harness commit by uv (``LINECASTER_HARNESS_ENVS``, default
``~/.cache/linecaster/harnesses``): the harness's source at the commit, a virtual environment of its Python, the
harness installed with its own pins, plus ``PINS`` where it leaves a package open that has since moved past what it
works with.
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
        "merge": "harness_merge_omnidocbench.py",
    },
}
#: the name the harness gives its result files (its prediction folder's, ``predictions``, and its match method)
SAVE = "predictions_quick_match"


def envs_root() -> Path:
    return Path(os.environ.get("LINECASTER_HARNESS_ENVS", Path.home() / ".cache/linecaster/harnesses"))


def environment(name: str) -> Path:
    """The harness's folder (its source and ``.venv``), built by uv the first time (one builder at a time)."""
    h = HARNESSES[name]
    root = envs_root() / f"{name}-{h['commit'][:8]}"
    if (root / ".linecaster-ready").exists():
        return root
    root.parent.mkdir(parents=True, exist_ok=True)
    with open(root.parent / f".{root.name}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (root / ".linecaster-ready").exists():
            return root
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
        python = root / ".venv/bin/python"
        subprocess.run([uv, "venv", "-q", "--python", h["python"], str(root / ".venv")], check=True)
        subprocess.run([uv, "pip", "install", "-q", "--python", str(python), "-e", str(root), *h["pins"]], check=True)
        (root / ".linecaster-ready").write_text(json.dumps({"commit": h["commit"], "pins": h["pins"]}))
    return root


def _attributes(gt) -> dict[str, str]:
    """A ground-truth page's slices as page attributes (``yes``/``no``), by which the harness groups pages."""
    from .render import text
    from .slices import page_slices

    sl = page_slices(gt, text(gt, "full"))
    return {k: "yes" if k in sl else "no" for k in ("tables", "table-heavy", "formulas")}


def write_shard(folder: str | Path, truth_rows: dict[str, dict], run_rows: dict[str, dict | None],
                transcription: str = "ocr_new", truth_transcription: str = "ground_truth") -> dict:
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
        pages.append(truth_page(pid, gt, attributes=_attributes(gt)))
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


def merge(name: str, out: str | Path, cdm: bool = False) -> dict:
    """The shards' results put together by the harness's own aggregation (``OUT/result/merged_metric_result.json``)."""
    out = Path(out).resolve()
    root = environment(name)
    cfg = config(out, cdm)                      # the modules and metrics merged (the paths in it are not read)
    script = Path(__file__).with_name(HARNESSES[name]["merge"])
    subprocess.run([str(root / ".venv/bin/python"), str(script), str(out), str(cfg)], cwd=root, check=True,
                   stdout=subprocess.DEVNULL)
    return json.loads((out / "result/merged_metric_result.json").read_text())


def finish(name: str, out: str | Path, pages: str, truth: str, transcription: str = "ocr_new",
           truth_transcription: str = "ground_truth", ids: set[str] | None = None, cdm: bool = False) -> dict:
    """After every shard: the ground-truth pages no shard has (the run lacks them) as one more shard of empty
    predictions, the merge, and ``OUT/harness.yaml`` (harness, commit, pins, inputs, counts, headline metrics)."""
    import datetime as dt

    import yaml

    from . import scorer
    from .run import _ID, read_truth

    out = Path(out).resolve()
    seen: set[str] = set()
    for t in sorted(out.glob("shards/*/truth.json")):
        seen |= {p["page_info"]["image_path"].removesuffix(".png") for p in json.loads(t.read_text())}
    wanted = ids if ids is not None else _truth_ids(truth)
    lacking = sorted(set(wanted) - seen)
    if lacking:
        folder = out / "shards" / "missing"
        shutil.rmtree(folder, ignore_errors=True)
        write_shard(folder, read_truth(truth, set(lacking)), {}, transcription, truth_transcription)
        logger.info("harness {}: {} ground-truth pages the run lacks, scored as empty predictions", name, len(lacking))
        run_shard(name, folder, cdm)
    result = merge(name, out, cdm)
    h = HARNESSES[name]
    record = {"schema": "linecaster.harness-run/1", "harness": name, "repo": h["repo"], "commit": h["commit"],
              "pins": h["pins"], "cdm": cdm, "pages": str(pages), "truth": str(truth),
              "transcription": transcription, "truth_transcription": truth_transcription,
              "counts": {"pages": len(seen) + len(lacking), "missing": len(lacking),
                         "shards": len(list(out.glob("shards/*/truth.json")))},
              "metrics": summarize(result), "exporter": scorer(), "date": dt.date.today().isoformat()}
    (out / "harness.yaml").write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True))
    return record


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
        workers: int = 8) -> dict:
    """The harness in one process on one shard of every page (``linecaster harness``: small sets; many pages: the
    pipeline ``harness.v1``)."""
    from .run import read_truth

    if name not in HARNESSES:
        raise ValueError(f"unknown harness {name!r}; known: {sorted(HARNESSES)}")
    out = Path(out).resolve()
    wanted = ids if ids is not None else _truth_ids(truth)
    shard = out / "shards" / "00000"
    shutil.rmtree(out / "shards", ignore_errors=True)
    write_shard(shard, read_truth(truth, set(wanted)), read_truth(pages, set(wanted)), transcription,
                truth_transcription)
    run_shard(name, shard, cdm, workers)
    return finish(name, out, pages, truth, transcription, truth_transcription, set(wanted), cdm)


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
