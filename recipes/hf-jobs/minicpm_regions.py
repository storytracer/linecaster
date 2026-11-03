# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["linecaster"]
#
# [tool.uv.sources]
# linecaster = { path = "../..", editable = true }
# ///
"""MiniCPM-OCR 1.0 as a region reader on Hugging Face Jobs: PP-DocLayoutV3 layout (``linecaster serve``)
→ ``ChatRegionStep(MiniCPMOCR)`` (vLLM) → page rows, both servers in each Job on its one GPU.
datatrove's JobsPipelineExecutor fans the pages out over Jobs; page rows and datatrove's logging_dir go
to the bucket. The page Markdown is assembled afterwards from the rows
(``linecaster.models.minicpm_ocr.assemble_markdown``, the SDK's own assembly).

    uv run recipes/hf-jobs/minicpm_regions.py --run-id minicpm-smoke-gt60 --commit <linecaster sha> \\
        --dataset <namespace>/<image dataset> --revision <sha> --tasks 1
    uv run recipes/hf-jobs/minicpm_regions.py ... --dry-run    # print the plan, pickle the pipeline

Image: ``cr.hf.co/davanstrien/minicpm-ocr:1.0-vllm-5d35ce3`` (the BHL board's MiniCPM-OCR image): vLLM
nightly 5d35ce3 (MiniCPM-OCR support and DSpark are not in a vLLM release yet) with transformers at
OpenBMB's pin, on ``vllm/vllm-openai``, so it qualifies for the executor like ``chat_page.py``'s image
(``uv`` on PATH, Python 3.12, ``vllm`` on PATH). Its SDK venv and baked Paddle layout model are not used.

Two environments, one GPU:

* vLLM runs in the image's own Python (torch and transformers as the image has them). ``ServeChatModel``
  starts it with ``outside_venv`` so the pipeline's uv environment does not leak into it. Model and
  DSpark draft are pulled at the pinned revisions; serve flags from OpenBMB's SDK tutorial (the spec's
  ``serve_args``).
* The pipeline and the layout server run in the uv environment the executor builds from
  ``dependencies(commit, engines="paddlex-tesseract")``: linecaster + linecaster-paddlex (PP-DocLayoutV3 on ONNX
  Runtime GPU with CUDA 13 libraries from the nvidia-* wheels); no kraken, so no git (the image has
  none) and no torch in that environment. ``ServeModels`` starts ``linecaster serve`` with it.

Both serving blocks go last (after the writer). The last block boots first: vLLM takes its
``--gpu-memory-utilization`` share and finishes its memory profiling before the layout server loads
into the rest (default 0.8 of an L4's 24 GB: about 4.5 GB stay for ONNX Runtime).

A self-contained uv script (Python 3.12, as on the Jobs). ``--commit`` must be pushed to GitHub.
"""
from __future__ import annotations

import argparse
import json

from linecaster.backends import Served
from linecaster.blocks.chat import ChatRegionStep
from linecaster.blocks.models import LayoutStep
from linecaster.blocks.readers import HFImageDatasetReader, ImageFolderReader
from linecaster.blocks.serve import ServeChatModel, ServeModels
from linecaster.blocks.writers import PageJsonlWriter
from linecaster.jobs import dependencies
from linecaster.models.minicpm_ocr import MiniCPMOCR

IMAGE = "cr.hf.co/davanstrien/minicpm-ocr:1.0-vllm-5d35ce3"
LAYOUT = [{"name": "layout", "spec": "linecaster_paddlex:PaddleLayoutModel", "kwargs": {"model_name": "PP-DocLayoutV3"}}]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--commit", required=True, help="linecaster commit the Jobs install (must be pushed)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--dataset"); src.add_argument("--images")
    ap.add_argument("--revision"); ap.add_argument("--id-column", default="PageID")
    ap.add_argument("--image", default=IMAGE)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.8,
                    help="vLLM's share of the GPU; the layout server takes the rest")
    ap.add_argument("--no-dspark", action="store_true", help="plain decoding (no speculative decoding)")
    ap.add_argument("--tasks", type=int, default=1); ap.add_argument("--workers", type=int, default=-1)
    ap.add_argument("--bucket", default="hf://buckets/finebooks/linecaster-runs")
    ap.add_argument("--namespace", default="finebooks"); ap.add_argument("--flavor", default="l4x1")
    ap.add_argument("--timeout", default="2h"); ap.add_argument("--limit", type=int, default=-1)
    ap.add_argument("--layout-window", type=int, default=16, help="max pages in flight at the layout server")
    ap.add_argument("--window", type=int, default=48, help="max region requests in flight at vLLM (Auto max_limit)")
    ap.add_argument("--initial-window", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true", help="print the plan and pickle the pipeline; launch nothing")
    a = ap.parse_args()
    if a.dataset and not a.revision:
        ap.error("--dataset needs a pinned --revision")

    spec = MiniCPMOCR()
    name = "minicpm-ocr-1.0"
    run = f"{a.bucket}/{a.run_id}"
    vllm_port, layout_port = 8000, 8100
    reader = (HFImageDatasetReader(a.dataset, a.revision, id_column=a.id_column, limit=a.limit) if a.dataset
              else ImageFolderReader(a.images, glob_pattern="**/*.webp", item_from_parent=True, limit=a.limit))
    speculative = [] if a.no_dspark else MiniCPMOCR.speculative_args(spec.draft_model, spec.draft_revision)
    vllm = ServeChatModel(spec, port=vllm_port, gpu_memory_utilization=a.gpu_memory_utilization,
                          extra_args=speculative, outside_venv=True)
    pipeline = [
        reader,
        LayoutStep(Served(f"http://127.0.0.1:{layout_port}/v1", model="layout", max_window=a.layout_window)),
        ChatRegionStep(spec, Served(f"http://127.0.0.1:{vllm_port}/v1", model=spec.served_name, max_window=a.window,
                                    initial_window=a.initial_window, read_timeout=1800.0)),
        PageJsonlWriter(f"{run}/processed/{name}", output_filename="${rank}.jsonl.gz"),
        ServeModels(LAYOUT, port=layout_port),   # boots second, after vLLM's memory profiling
        vllm,                                    # last: boots first, lives until every page is written
    ]
    deps = dependencies(a.commit, engines="paddlex-tesseract")
    if a.dry_run:
        import dill

        blob = dill.dumps(pipeline)
        print(json.dumps({"run": run, "image": a.image, "flavor": a.flavor, "dependencies": deps,
                          "vllm": vllm.command(), "pipeline": [type(s).__name__ for s in pipeline],
                          "pickled_bytes": len(blob)}, indent=1))
        return

    from datatrove.executor import JobsPipelineExecutor

    JobsPipelineExecutor(pipeline, tasks=a.tasks, workers=a.workers, logging_dir=f"{run}/logs/{name}",
                         flavor=a.flavor, namespace=a.namespace, image=a.image, dependencies=deps,
                         timeout=a.timeout, python="3.12", job_name=f"linecaster-{a.run_id}",
                         labels={"project": "linecaster"}, env={"LINECASTER_RUN": a.run_id}).run()
    print(json.dumps({"run": run, "commit": a.commit, "image": a.image}))


if __name__ == "__main__":
    main()
