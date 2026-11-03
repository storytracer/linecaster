"""The squiddle combination on a Ray cluster: one datatrove task per GPU, each task starting its own
``linecaster serve`` (layout, lines, recognition, tables, formulas) on its GPU and running the chain through
saturate against it. Images from a folder (local or shared), page rows and datatrove's logging_dir to a
folder every node can reach.

    ray start --head --num-gpus 8                  # on each machine (workers: ray start --address=<head>:6379)
    .venv/bin/python recipes/ray/squiddle_chain.py IMAGES OUT --tasks 64
    ray stop

Run it from linecaster's core environment with the ``ray`` extra (``uv sync --extra ray``). The servers run
in the engine environment, ``envs/kraken-paddlex`` by default (``--engine-python``).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from linecaster.backends import Served
from linecaster.blocks.document import AssembleDocument, Typography
from linecaster.blocks.lines import AssignLinesToRegions
from linecaster.blocks.models import FormulasStep, LayoutStep, LinesStep, RecognitionStep, TablesStep
from linecaster.blocks.readers import ImageFolderReader
from linecaster.blocks.serve import ServeModels
from linecaster.blocks.unicode import NormalizeUnicode
from linecaster.blocks.writers import PageJsonlWriter
from linecaster.ray_executor import RayGPUExecutor

REPO = Path(__file__).resolve().parents[2]
MODELS = [
    {"name": "layout", "spec": "linecaster_paddlex:PaddleLayoutModel", "kwargs": {"model_name": "PP-DocLayoutV3"}},
    {"name": "lines", "spec": "linecaster_paddlex:PaddleLineModel", "kwargs": {"model_name": "PP-OCRv6_medium_det"}},
    {"name": "recognition", "spec": "linecaster_kraken:KrakenRecognitionModel", "kwargs": {"model": "medium", "batch_size": 8}},
    {"name": "tables", "spec": "linecaster_paddlex:PaddleTableModel", "kwargs": {}},
    {"name": "formulas", "spec": "linecaster_paddlex:PaddleFormulaModel", "kwargs": {}},
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("images"); ap.add_argument("out")
    ap.add_argument("--tasks", type=int, required=True, help="datatrove tasks (one GPU each at a time)")
    ap.add_argument("--glob", default="**/*.webp")
    ap.add_argument("--engine-python", default=str(REPO / "envs/kraken-paddlex/.venv/bin/python"))
    ap.add_argument("--cpus-per-task", type=int, default=12)
    ap.add_argument("--mem-per-cpu-gb", type=float, default=4)
    ap.add_argument("--base-port", type=int, default=8100)
    ap.add_argument("--address", default="auto", help="Ray cluster address for ray.init")
    a = ap.parse_args()

    import ray

    ray.init(address=a.address)
    endpoint = f"http://127.0.0.1:{a.base_port}/v1"      # moved to base_port + GPU index in each task
    b = {m["name"]: Served(endpoint, model=m["name"]) for m in MODELS}
    pipeline = [
        ImageFolderReader(a.images, glob_pattern=a.glob, item_from_parent=True),
        LayoutStep(b["layout"]),
        LinesStep(b["lines"]),
        AssignLinesToRegions(),
        RecognitionStep(b["recognition"]),
        NormalizeUnicode(),
        TablesStep(b["tables"]),
        FormulasStep(b["formulas"]),
        Typography(),
        AssembleDocument(),
        PageJsonlWriter(f"{a.out}/rows", output_filename="${rank}.jsonl", compression=None),
        ServeModels(MODELS, port=a.base_port, python=a.engine_python),   # last: lives until every page is written
    ]
    RayGPUExecutor(pipeline, tasks=a.tasks, cpus_per_task=a.cpus_per_task, mem_per_cpu_gb=a.mem_per_cpu_gb,
                   base_port=a.base_port, logging_dir=f"{a.out}/logs").run()


if __name__ == "__main__":
    main()
