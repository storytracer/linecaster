"""OmniDocBench's end-to-end results of many shards put together as its harness would have computed them on all their
pages at once. Run by the harness's own Python (``linecaster.scoring.harness.merge``), never imported by linecaster:

    <harness>/.venv/bin/python harness_merge_omnidocbench.py OUT CONFIG

The harness computes every result from its per-sample records (``result/*_<module>_result.json``: each matched element
with its metrics, ``Edit_num``, ``upper_len`` and page): this script concatenates the shards' samples and applies the
harness's own aggregation to them: ``End2EndDataset._collect_gt_pages_by_element`` (the pages that count for a
module), ``get_full_labels_results`` (groups), ``get_page_split`` (page groups), and for ``all`` the same lines as
its ``call_Edit_dist`` and ``call_TEDS`` (an average over samples; summed in another order, so equal to the last
bits of a float). It writes ``OUT/result/merged_metric_result.json``."""
import glob
import json
import os
import sys

import yaml

SAVE = "predictions_quick_match"


def edit_dist(samples):
    """``call_Edit_dist.evaluate``'s result on samples that already carry ``Edit_num`` and ``upper_len``."""
    import pandas as pd

    df = pd.DataFrame([s for s in samples])
    if df.empty or "Edit_num" not in df:
        return {"Edit_dist": {"ALL_page_avg": "NaN"}}
    up_total_avg = df.groupby("image_name").apply(lambda x: x["Edit_num"].sum() / x["upper_len"].sum())
    all_total_avg = df["Edit_num"].sum() / df["upper_len"].sum()
    df["ratio"] = df["Edit_num"] / df["upper_len"]
    return {"Edit_dist": {"ALL_page_avg": up_total_avg.mean(), "edit_whole": all_total_avg,
                          "edit_sample_avg": df["ratio"].mean()}}


def teds(samples):
    """``call_TEDS.evaluate``'s result (group ``all``) from the samples' own TEDS scores."""
    def avg(xs):
        return sum(xs) / len(xs) if xs else "NaN"

    return {"TEDS": {"all": avg([s["metric"]["TEDS"] for s in samples if "TEDS" in (s.get("metric") or {})])},
            "TEDS_structure_only": {"all": avg([s["metric"]["TEDS_structure_only"] for s in samples
                                                if "TEDS_structure_only" in (s.get("metric") or {})])}}


def main(out, config):
    from src.core.metrics import get_full_labels_results, get_page_split    # the harness's own (its venv)
    from src.dataset.end2end_dataset import End2EndDataset

    cfg = yaml.safe_load(open(config))["end2end_eval"]["metrics"]
    shards = sorted(glob.glob(os.path.join(out, "shards", "*", "")))
    pages = [p for s in shards for p in json.load(open(os.path.join(s, "truth.json")))]
    page_info = {os.path.basename(p["page_info"]["image_path"]): p["page_info"]["page_attribute"] for p in pages}
    gt_pages = End2EndDataset._collect_gt_pages_by_element(None, pages)
    merged = {}
    for element, mcfg in cfg.items():
        samples = []
        for s in shards:
            path = os.path.join(s, "result", f"{SAVE}_{element}_result.json")
            if os.path.exists(path):
                samples += json.load(open(path))
        result = {}
        for metric in mcfg["metric"]:
            if metric == "Edit_dist":
                result.update(edit_dist(samples))
            elif metric == "TEDS":
                result.update(teds(samples))
            else:
                raise ValueError(f"merging {metric} across shards is not supported")
        merged[element] = {"all": result, "group": get_full_labels_results(samples),
                           "page": get_page_split(samples, page_info, gt_page_names=gt_pages.get(element),
                                                  expected_metrics=mcfg["metric"])}
    os.makedirs(os.path.join(out, "result"), exist_ok=True)
    with open(os.path.join(out, "result", "merged_metric_result.json"), "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False, default=float)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
