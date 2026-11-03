"""Layout model + a chat VLM per region: PP-DocLayoutV3 regions (linecaster serve) and an OpenAI-compatible
VLM reading each region's crop (e.g. vLLM with LightOnOCR-2-1B), both through saturate.

    .venv/bin/python examples/chat_regions.py IMAGES OUT --layout http://127.0.0.1:8100/v1 \
        --vlm http://127.0.0.1:8132/v1 --model lightonai/LightOnOCR-2-1B
"""
from __future__ import annotations

import argparse

from datatrove.executor import LocalPipelineExecutor

from linecaster.backends import Served
from linecaster.blocks.chat import ChatRegionStep
from linecaster.blocks.models import LayoutStep
from linecaster.blocks.readers import ImageFolderReader
from linecaster.blocks.writers import PageJsonlWriter
from linecaster.models import chat_model

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("images"); ap.add_argument("out")
    ap.add_argument("--layout", default="http://127.0.0.1:8100/v1")
    ap.add_argument("--vlm", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="lightonai/LightOnOCR-2-1B")
    ap.add_argument("--window", type=int, default=48)
    ap.add_argument("--tasks", type=int, default=1)
    a = ap.parse_args()
    spec = chat_model(a.model)
    LocalPipelineExecutor([
        ImageFolderReader(a.images),
        LayoutStep(Served(a.layout, "layout")),
        ChatRegionStep(spec, Served(a.vlm, model=spec.model, max_window=a.window, initial_window=8)),
        PageJsonlWriter(a.out, output_filename="${rank}.jsonl", compression=None),
    ], tasks=a.tasks, workers=a.tasks, logging_dir=f"{a.out}/logs").run()
