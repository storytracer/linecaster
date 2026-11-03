"""Page recognition with a chat VLM (default lightonai/LightOnOCR-2-1B) on Hugging Face Jobs: datatrove's
JobsPipelineExecutor fans the pages out over Jobs; each Job starts vLLM (or SGLang) on its GPU (``ServeChatModel``,
last in the pipeline) and runs ``ChatPageStep`` through saturate against it. Inputs: an image dataset
on the Hub (pinned revision) or an image folder (``hf://...``); page rows and datatrove's logging_dir
go to the bucket.

    .venv/bin/python recipes/hf-jobs/chat_page.py --run-id lighton2-smoke-gt60 --commit <linecaster sha> \
        --dataset <namespace>/<image dataset> --revision <sha> --tasks 1

Image: ``vllm/vllm-openai:v0.26.0`` (the BHL board's vLLM for this model). It qualifies for the executor:
it has ``uv`` (``pip install uv`` in vLLM's Dockerfile) and Python 3.12 (``PYTHON_VERSION=3.12``), and
the ``vllm`` command on PATH (its entrypoint is ``vllm serve``). The pipeline itself runs in the uv
environment the executor builds from ``dependencies`` (linecaster at ``--commit``: datatrove, saturate,
Pillow; no vLLM, no torch), with ``--python 3.12`` so the dill-pickled pipeline loads; ``ServeChatModel``
starts the image's own ``vllm`` as a subprocess. That is the arrangement of Daniel's uv-scripts recipes
(``hf jobs uv run --image vllm/vllm-openai:<tag> ...``), with datatrove around it.

SGLang specs (``spec.server == "sglang"``, e.g. baidu/Unlimited-OCR-2): pass the SGLang image the spec
names (``--image lmsysorg/sglang:v0.5.20-cu130``). ``ServeChatModel`` then runs with ``outside_venv``: it
finds the image's own ``python3`` (``/opt/sglang/bin``, past the pipeline's uv environment), installs the
spec's ``server_packages`` into it, checks the pin and starts ``python3 -m sglang.launch_server``. The
image has uv and Python 3.12 (``/opt/sglang``) like the vLLM one. ``--gpu-memory-utilization`` defaults to
0.8 for vLLM and to the spec's own ``--mem-fraction-static`` for SGLang.

    .venv/bin/python recipes/hf-jobs/chat_page.py ... --dry-run    # print the plan, pickle the pipeline

Run it from linecaster's core environment (Python 3.12). ``--commit`` must be pushed to GitHub.
"""
from __future__ import annotations

import argparse
import json

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
    ap.add_argument("--gpu-memory-utilization", type=float, default=None,
                    help="vLLM: default 0.8, the board's value; SGLang: --mem-fraction-static, default the spec's")
    ap.add_argument("--tasks", type=int, default=1); ap.add_argument("--workers", type=int, default=-1)
    ap.add_argument("--bucket", default="hf://buckets/finebooks/linecaster-runs")
    ap.add_argument("--namespace", default="finebooks"); ap.add_argument("--flavor", default="l4x1")
    ap.add_argument("--timeout", default="2h"); ap.add_argument("--limit", type=int, default=-1)
    ap.add_argument("--window", type=int, default=48, help="max pages in flight (Auto max_limit)")
    ap.add_argument("--initial-window", type=int, default=8)
    ap.add_argument("--read-timeout", type=float, default=1800.0, help="seconds per request")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and pickle the pipeline; launch nothing")
    a = ap.parse_args()
    if a.dataset and not a.revision:
        ap.error("--dataset needs a pinned --revision")

    spec = chat_model(a.model)
    name = a.model.rsplit("/", 1)[-1].lower()
    run = f"{a.bucket}/{a.run_id}"
    port = 8000
    sglang = spec.server == "sglang"
    gmu = a.gpu_memory_utilization if a.gpu_memory_utilization is not None or sglang else 0.8
    serve = ServeChatModel(spec, port=port, gpu_memory_utilization=gmu, outside_venv=sglang)
    reader = (HFImageDatasetReader(a.dataset, a.revision, id_column=a.id_column, limit=a.limit) if a.dataset
              else ImageFolderReader(a.images, glob_pattern="**/*.webp", item_from_parent=True, limit=a.limit))
    pipeline = [
        reader,
        ChatPageStep(spec, Served(f"http://127.0.0.1:{port}/v1", model=spec.served_name, max_window=a.window,
                                  initial_window=a.initial_window, read_timeout=a.read_timeout)),
        PageJsonlWriter(f"{run}/processed/{name}", output_filename="${rank}.jsonl.gz"),
        serve,   # last
    ]
    deps = dependencies(a.commit, engines=False)
    if a.dry_run:
        import dill

        blob = dill.dumps(pipeline)
        print(json.dumps({"run": run, "image": a.image, "flavor": a.flavor, "dependencies": deps,
                          "server": serve.launch_command(), "install": serve.install_commands(serve.python),
                          "pipeline": [type(s).__name__ for s in pipeline], "pickled_bytes": len(blob)}, indent=1))
        return

    from datatrove.executor import JobsPipelineExecutor

    JobsPipelineExecutor(pipeline, tasks=a.tasks, workers=a.workers, logging_dir=f"{run}/logs/{name}",
                         flavor=a.flavor, namespace=a.namespace, image=a.image, dependencies=deps,
                         timeout=a.timeout, python="3.12", job_name=f"linecaster-{a.run_id}",
                         labels={"project": "linecaster"}, env={"LINECASTER_RUN": a.run_id}).run()
    print(json.dumps({"run": run, "commit": a.commit, "image": a.image}))


if __name__ == "__main__":
    main()
