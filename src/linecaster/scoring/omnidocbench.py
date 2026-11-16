"""OmniDocBench's end-to-end evaluation in linecaster's own process: its code, imported, on pages in memory.

linecaster writes the two sides in OmniDocBench's formats (``linecaster.formats.omnidocbench``) and calls the
harness's own functions on them, at the pinned commit (``linecaster.scoring.harness.HARNESSES``; the source fetched
once into the cache and put on the import path, ``load``): per page ``End2EndDataset.process_get_matched_elements``
(its matching, on a matcher set up with the harness's defaults, ``matcher``), per task ``get_matched_elements`` and
the metric classes (``Edit_dist``, ``TEDS``) on the task's pages, as the harness's ``End2EndEval`` runs them
(``score_pages``); and when every task is done ``get_full_labels_results`` and ``get_page_split`` on every page's
samples, with the corpus averages of ``call_Edit_dist`` and ``call_TEDS`` (``aggregate``). The harness's results do
not depend on how its pages are grouped (it matches and scores each page alone), so they equal one run of the harness
on every page; ``tests`` and the parity check (``linecaster harness``, the pinned harness unchanged in its own
environment) hold it to that.

The harness's packages are its own pins' successors (the pipeline script lists them): Python 3.12, NumPy 2, pandas 3.
Its import name is ``src``: it is loaded only in the scoring pipeline's environment.
"""
from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from typing import Any

NAME = "omnidocbench"
#: the modules scored and their metrics (OmniDocBench's end-to-end config without CDM)
MODULES: dict[str, list[str]] = {"text_block": ["Edit_dist"], "display_formula": ["Edit_dist"],
                                 "table": ["TEDS", "Edit_dist"], "reading_order": ["Edit_dist"]}


def load() -> None:
    """The harness's source on the import path (fetched once, ``linecaster.scoring.harness.source``)."""
    from .harness import source

    root = str(source(NAME))
    if root not in sys.path:
        sys.path.insert(0, root)


def matcher():
    """OmniDocBench's ``End2EndDataset`` set up as its ``__init__`` sets it up from a config that names none of its
    options (its defaults: quick match, its timeouts and fallbacks), without loading files or matching."""
    from threading import Lock

    load()
    from src.dataset.end2end_dataset import End2EndDataset

    m = object.__new__(End2EndDataset)
    m.match_method = "quick_match"
    m.enable_timeout_match_fallback = True
    m.match_timeout_sec = 420
    m.quick_match_truncated_timeout_sec = 300
    m.timeout_fallback_short_line_max_chars = None
    m.timeout_fallback_target_chunk_chars = None
    m.timeout_fallback_max_chunk_chars = None
    m.timeout_fallback_max_chunk_span = 10
    m.timeout_fallback_order_window = None
    m.timeout_fallback_order_penalty = 0.10
    m.match_workers = 1
    m.slow_stage_log_sec = 60.0
    m._match_debug_lock = Lock()
    m.match_debug_info = {"workers": 1, "page_count": 0, "quick_match_truncated_timeout_sec": 300,
                          "match_timeout_sec": 420,
                          "text_match_fallback_pages": {"quick_match_timeout": set(), "page_timeout": set()}}
    return m


@contextlib.contextmanager
def _in(folder: str):
    old = os.getcwd()
    os.chdir(folder)                     # the metric classes write ./result/*.json: kept out of the run's folder
    try:
        yield
    finally:
        os.chdir(old)


def score_pages(pages: list[tuple[dict, str]]) -> dict[str, list[dict]]:
    """The harness on ``pages`` (each: its ground truth as an OmniDocBench page, the prediction's Markdown): every
    module's samples (``MODULES``), each with its metrics, as the harness's ``End2EndEval`` leaves them."""
    load()
    from src.core.preprocess import latex_timeout_context
    from src.core.registry import METRIC_REGISTRY
    import src.metrics  # noqa: F401  (registers the metric classes)

    m = matcher()
    results = []
    for i, (gt, md) in enumerate(pages):
        name = os.path.basename(gt["page_info"]["image_path"])
        with latex_timeout_context(img_name=name, pred_path=None):
            results.append({"index": i, "img_name": name, "pred_path": None,
                            "result": m.process_get_matched_elements(gt, md, name)})
    m._collect_page_matches = lambda gt_samples, pred_folder: results         # the pages, matched above
    matched = m.get_matched_elements([gt for gt, _ in pages], None)
    out: dict[str, list[dict]] = {}
    with tempfile.TemporaryDirectory() as tmp, _in(tmp):
        os.makedirs("result")                    # as the harness's End2EndEval makes it before its metrics
        for element, metrics in MODULES.items():
            samples = matched[element]
            for metric in metrics:
                samples, _ = METRIC_REGISTRY.get(metric)(samples, {"metric": metrics, "teds_workers": 1}).evaluate(
                    [], f"task_{element}")
            out[element] = list(samples if isinstance(samples, list) else samples.samples)
    return out


def page_key(sample: dict) -> str:
    """The page a sample belongs to (the harness's own rule, ``get_page_split``)."""
    img = str(sample["img_id"])
    return img if img.endswith((".jpg", ".png")) else "_".join(img.split("_")[:-1])


def page_summary(gt: dict) -> dict:
    """What the aggregation needs of a ground-truth page: its name, attributes and categories."""
    return {"image_path": gt["page_info"]["image_path"], "page_attribute": gt["page_info"]["page_attribute"],
            "categories": [{"category_type": d["category_type"], "ignore": d.get("ignore", False)}
                           for d in gt["layout_dets"]]}


def _edit_dist(samples: list[dict]) -> dict:
    """``call_Edit_dist.evaluate``'s corpus averages, on samples that already carry ``Edit_num`` and ``upper_len``."""
    import pandas as pd

    df = pd.DataFrame(samples)
    if df.empty or "Edit_num" not in df:
        return {"Edit_dist": {"ALL_page_avg": "NaN"}}
    up_total_avg = df.groupby("image_name").apply(lambda x: x["Edit_num"].sum() / x["upper_len"].sum())
    return {"Edit_dist": {"ALL_page_avg": float(up_total_avg.mean()),
                          "edit_whole": float(df["Edit_num"].sum() / df["upper_len"].sum()),
                          "edit_sample_avg": float((df["Edit_num"] / df["upper_len"]).mean())}}


def _teds(samples: list[dict]) -> dict:
    """``call_TEDS.evaluate``'s ``all``: the mean of the samples' TEDS and TEDS-S."""
    def avg(key):
        xs = [s["metric"][key] for s in samples if key in (s.get("metric") or {})]
        return sum(xs) / len(xs) if xs else "NaN"

    return {"TEDS": {"all": avg("TEDS")}, "TEDS_structure_only": {"all": avg("TEDS_structure_only")}}


def aggregate(samples: dict[str, list[dict]], pages: list[dict]) -> dict[str, Any]:
    """The harness's result (its ``*_metric_result.json``: per module ``all``, ``group`` and ``page``) from every
    page's samples (``score_pages``) and ``pages`` (``page_summary`` of each ground-truth page)."""
    load()
    from src.core.metrics import get_full_labels_results, get_page_split
    from src.dataset.end2end_dataset import End2EndDataset

    page_info = {os.path.basename(p["image_path"]): p["page_attribute"] for p in pages}
    gt_pages = End2EndDataset._collect_gt_pages_by_element(
        None, [{"page_info": {"image_path": p["image_path"]}, "layout_dets": p["categories"]} for p in pages])
    result: dict[str, Any] = {}
    for element, metrics in MODULES.items():
        ss = samples.get(element, [])
        all_: dict = {}
        for metric in metrics:
            all_.update(_edit_dist(ss) if metric == "Edit_dist" else _teds(ss))
        result[element] = {"all": all_, "group": get_full_labels_results(ss),
                           "page": get_page_split(ss, page_info, gt_page_names=gt_pages.get(element),
                                                  expected_metrics=metrics)}
    return result
