# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["linecaster"]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# ///
"""Page recognition with a chat VLM (default lightonai/LightOnOCR-2-1B) as a linecaster pipeline:
image folder -> ChatPageStep (through saturate against an OpenAI-compatible server) -> page rows.

    # against a server you started (e.g. vllm serve ... --port 8000):
    uv run examples/chat_page.py IMAGES OUT --endpoint http://127.0.0.1:8000/v1
    # or let the task start vLLM itself (needs `vllm` on PATH and a GPU):
    uv run examples/chat_page.py IMAGES OUT --serve --gpu-memory-utilization 0.5

Window: Auto(initial=8, max_limit=48), the uv-scripts recipe's setting (the BHL board driver used
max_limit 12; on spark the recipe setting is ~29 % faster on one engine, see NOTES.md).
"""
from __future__ import annotations

import argparse

from datatrove.executor import LocalPipelineExecutor

from linecaster.backends import Served
from linecaster.blocks.chat import ChatPageStep
from linecaster.blocks.readers import ImageFolderReader
from linecaster.blocks.serve import ServeChatModel
from linecaster.blocks.writers import PageJsonlWriter
from linecaster.models import chat_model


def pipeline(images: str, out: str, model: str = "lightonai/LightOnOCR-2-1B", endpoint: str = "http://127.0.0.1:8000/v1",
             window: int = 48, initial_window: int = 8, prepare_workers: int = 4, serve: bool = False, port: int = 8000,
             gpu_memory_utilization: float | None = None, limit: int = -1, transcription: str = "ocr",
             vllm: str = "vllm"):
    spec = chat_model(model)
    if serve:
        endpoint = f"http://127.0.0.1:{port}/v1"
    steps = [
        ImageFolderReader(images, limit=limit),
        ChatPageStep(spec, Served(endpoint, model=spec.model, max_window=window, initial_window=initial_window,
                                  read_timeout=1800.0),
                     transcription, prepare_workers=prepare_workers),
        PageJsonlWriter(out, output_filename="${rank}.jsonl", compression=None),
    ]
    if serve:   # last: lives until every page is written
        steps.append(ServeChatModel(spec, port=port, gpu_memory_utilization=gpu_memory_utilization, vllm=vllm))
    return steps


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("images"); ap.add_argument("out")
    ap.add_argument("--model", default="lightonai/LightOnOCR-2-1B")
    ap.add_argument("--endpoint", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--window", type=int, default=48); ap.add_argument("--initial-window", type=int, default=8)
    ap.add_argument("--prepare-workers", type=int, default=4)
    ap.add_argument("--serve", action="store_true"); ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--gpu-memory-utilization", type=float, default=None)
    ap.add_argument("--vllm", default="vllm", help="the vllm command (with --serve)")
    ap.add_argument("--limit", type=int, default=-1)
    ap.add_argument("--tasks", type=int, default=1); ap.add_argument("--logs", default=None)
    a = ap.parse_args()
    LocalPipelineExecutor(pipeline(a.images, a.out, a.model, a.endpoint, a.window, a.initial_window, a.prepare_workers,
                                   a.serve, a.port, a.gpu_memory_utilization, a.limit, vllm=a.vllm),
                          tasks=a.tasks, workers=a.tasks, logging_dir=a.logs or f"{a.out}/logs").run()
