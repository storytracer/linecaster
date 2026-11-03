"""The squiddle combination on Hugging Face Jobs: datatrove's JobsPipelineExecutor fans the pages out
over Jobs; each Job starts ``linecaster serve`` (layout, lines, recognition models on its GPU) and runs
the chain through saturate against it. Inputs: an image dataset on the Hub or an image folder
(``hf://...``); outputs and datatrove's logging_dir in a bucket.

    .venv/bin/python recipes/hf-jobs/squiddle_chain.py --run-id smoke-gt60 --commit <linecaster sha> \
        --dataset <namespace>/<image dataset> --revision <sha> --tasks 1
    .venv/bin/python recipes/hf-jobs/squiddle_chain.py --run-id gt2165 --commit <sha> \
        --images hf://datasets/finebooks/bhl-impact-gt@<rev>/images --tasks 4

Run it from linecaster's core environment (Python 3.12: datatrove pickles the pipeline with dill, so
launcher and Jobs need the same minor version).
"""
from __future__ import annotations

import argparse
import json

from datatrove.executor import JobsPipelineExecutor

from linecaster.backends import Served
from linecaster.blocks.lines import AssignLinesToRegions
from linecaster.blocks.models import LayoutStep, LinesStep, RecognitionStep, TablesStep
from linecaster.blocks.readers import HFImageDatasetReader, ImageFolderReader
from linecaster.blocks.serve import ServeModels
from linecaster.blocks.writers import PageJsonlWriter
from linecaster.jobs import dependencies

MODELS = [
    {"name": "layout", "spec": "linecaster_paddlex:PaddleLayoutModel", "kwargs": {"model_name": "PP-DocLayoutV3"}},
    {"name": "lines", "spec": "linecaster_paddlex:PaddleLineModel", "kwargs": {"model_name": "PP-OCRv6_medium_det"}},
    {"name": "recognition", "spec": "linecaster_kraken:KrakenRecognitionModel", "kwargs": {"model": "medium", "batch_size": 8}},
    {"name": "tables", "spec": "linecaster_paddlex:PaddleTableModel", "kwargs": {}},
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--commit", required=True, help="linecaster commit the Jobs install (must be pushed)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--dataset"); src.add_argument("--images")
    ap.add_argument("--revision"); ap.add_argument("--id-column", default="PageID")
    ap.add_argument("--tasks", type=int, default=1); ap.add_argument("--workers", type=int, default=-1)
    ap.add_argument("--bucket", default="hf://buckets/finebooks/linecaster-runs")
    ap.add_argument("--namespace", default="finebooks"); ap.add_argument("--flavor", default="l4x1")
    ap.add_argument("--timeout", default="3h"); ap.add_argument("--limit", type=int, default=-1)
    ap.add_argument("--window", type=int, default=32, help="max pages in flight per model block")
    a = ap.parse_args()

    run = f"{a.bucket}/{a.run_id}"
    reader = (HFImageDatasetReader(a.dataset, a.revision, id_column=a.id_column, limit=a.limit) if a.dataset
              else ImageFolderReader(a.images, glob_pattern="**/*.webp", item_from_parent=True, limit=a.limit))
    endpoint = "http://127.0.0.1:8100/v1"
    served = {m["name"]: Served(endpoint, model=m["name"], max_window=a.window) for m in MODELS}
    pipeline = [
        reader,
        LayoutStep(served["layout"]),
        LinesStep(served["lines"]),
        AssignLinesToRegions(),
        RecognitionStep(served["recognition"]),
        TablesStep(served["tables"]),
        PageJsonlWriter(f"{run}/processed/squiddle", output_filename="${rank}.jsonl.gz"),
        ServeModels(MODELS, port=8100),   # last: lives until every page is written (see the block's docstring)
    ]
    JobsPipelineExecutor(pipeline, tasks=a.tasks, workers=a.workers, logging_dir=f"{run}/logs/squiddle",
                         flavor=a.flavor, namespace=a.namespace, dependencies=dependencies(a.commit), timeout=a.timeout,
                         python="3.12", job_name=f"linecaster-{a.run_id}", labels={"project": "linecaster"},
                         env={"LINECASTER_RUN": a.run_id}).run()
    print(json.dumps({"run": run, "commit": a.commit}))


if __name__ == "__main__":
    main()
