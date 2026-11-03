"""Page recognition with a chat VLM (default lightonai/LightOnOCR-2-1B) on Hugging Face Jobs: datatrove's
JobsPipelineExecutor fans the pages out over Jobs; each Job starts vLLM on its GPU (``ServeChatModel``,
last in the pipeline) and runs ``ChatPageStep`` through saturate against it. Inputs: an image dataset
on the Hub (pinned revision) or an image folder (``hf://...``); page rows and datatrove's logging_dir
go to the bucket.

    .venv/bin/python recipes/hf-jobs/chat_page.py --run-id lighton2-smoke-gt60 --commit <linecaster sha> \
        --dataset finebooks/bhl-ocr-eval-sample-60 --revision 41ff347552d13967c5d3001ca3eada800b0c22d7 --tasks 1

Image: ``vllm/vllm-openai:v0.26.0`` (the BHL board's vLLM for this model). It qualifies for the executor:
it has ``uv`` (``pip install uv`` in vLLM's Dockerfile) and Python 3.12 (``PYTHON_VERSION=3.12``), and
the ``vllm`` command on PATH (its entrypoint is ``vllm serve``). The pipeline itself runs in the uv
environment the executor builds from ``dependencies`` (linecaster at ``--commit``: datatrove, saturate,
Pillow; no vLLM, no torch), with ``--python 3.12`` so the dill-pickled pipeline loads; ``ServeChatModel``
starts the image's own ``vllm`` as a subprocess. That is the arrangement of Daniel's uv-scripts recipes
(``hf jobs uv run --image vllm/vllm-openai:<tag> ...``), with datatrove around it.

Run it from linecaster's core environment (Python 3.12). ``--commit`` must be pushed to GitHub.
"""
from __future__ import annotations

import argparse
import json

from datatrove.executor import JobsPipelineExecutor

from linecaster.backends import Served
from linecaster.blocks.chat import ChatPageStep
from linecaster.blocks.readers import HFImageDatasetReader, ImageFolderReader
from linecaster.blocks.serve import ServeChatModel
from linecaster.blocks.writers import PageJsonlWriter
from linecaster.jobs import dependencies
from linecaster.models import chat_model

VLLM_IMAGE = "vllm/vllm-openai:v0.26.0"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--commit", required=True, help="linecaster commit the Jobs install (must be pushed)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--dataset"); src.add_argument("--images")
    ap.add_argument("--revision"); ap.add_argument("--id-column", default="PageID")
    ap.add_argument("--model", default="lightonai/LightOnOCR-2-1B")
    ap.add_argument("--image", default=VLLM_IMAGE)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.8, help="the board's value (L4: 24 GB)")
    ap.add_argument("--tasks", type=int, default=1); ap.add_argument("--workers", type=int, default=-1)
    ap.add_argument("--bucket", default="hf://buckets/finebooks/linecaster-runs")
    ap.add_argument("--namespace", default="finebooks"); ap.add_argument("--flavor", default="l4x1")
    ap.add_argument("--timeout", default="2h"); ap.add_argument("--limit", type=int, default=-1)
    ap.add_argument("--window", type=int, default=48, help="max pages in flight (Auto max_limit)")
    ap.add_argument("--initial-window", type=int, default=8)
    a = ap.parse_args()
    if a.dataset and not a.revision:
        ap.error("--dataset needs a pinned --revision")

    spec = chat_model(a.model)
    name = a.model.rsplit("/", 1)[-1].lower()
    run = f"{a.bucket}/{a.run_id}"
    port = 8000
    reader = (HFImageDatasetReader(a.dataset, a.revision, id_column=a.id_column, limit=a.limit) if a.dataset
              else ImageFolderReader(a.images, glob_pattern="**/*.webp", item_from_parent=True, limit=a.limit))
    pipeline = [
        reader,
        ChatPageStep(spec, Served(f"http://127.0.0.1:{port}/v1", model=spec.model, max_window=a.window,
                                  initial_window=a.initial_window, read_timeout=1800.0)),
        PageJsonlWriter(f"{run}/processed/{name}", output_filename="${rank}.jsonl.gz"),
        ServeChatModel(spec, port=port, gpu_memory_utilization=a.gpu_memory_utilization),   # last
    ]
    JobsPipelineExecutor(pipeline, tasks=a.tasks, workers=a.workers, logging_dir=f"{run}/logs/{name}",
                         flavor=a.flavor, namespace=a.namespace, image=a.image, dependencies=dependencies(a.commit, engines=False),
                         timeout=a.timeout, python="3.12", job_name=f"linecaster-{a.run_id}",
                         labels={"project": "linecaster"}, env={"LINECASTER_RUN": a.run_id}).run()
    print(json.dumps({"run": run, "commit": a.commit, "image": a.image}))


if __name__ == "__main__":
    main()
