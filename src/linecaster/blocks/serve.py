"""Blocks that host models for a task's served blocks: ``ServeModels`` starts ``linecaster serve``,
``ServeChatModel`` starts vLLM for a ``ChatPageStep`` (both through saturate's ``Engine``) when the
task starts, and stops it when all its pages are through. For a pipeline that brings
its own GPU, e.g. one HF Job per datatrove task.

Put it **last** in the pipeline (after the writer): datatrove chains generators, so the last block's
generator is the one that lives until every page has passed every block. Placed before the served
blocks, it would stop the server as soon as the reader ran dry, with requests still in flight."""
from __future__ import annotations

from datatrove.pipeline.base import PipelineStep


class ServeModels(PipelineStep):
    type = "🔠 - LINECASTER"
    name = "🖥️ serve models"

    def __init__(self, models: list[dict], port: int = 8100, python: str | None = None, boot_timeout: int = 1800,
                 max_queue: int = 16):
        super().__init__()
        self.models, self.port, self.python, self.boot_timeout, self.max_queue = models, port, python, boot_timeout, max_queue

    def run(self, data, rank: int = 0, world_size: int = 1):
        from ..serve import engine

        with self.track_time("boot"):
            server = engine(self.models, self.port, self.python, self.boot_timeout, self.max_queue)
            server.__enter__()
        try:
            yield from data
        finally:
            server.__exit__(None, None, None)


class ServeChatModel(PipelineStep):
    """Start a chat VLM server (vLLM) for a task's ``ChatPageStep``, through saturate's ``Engine``:
    ``vllm serve <spec.model> --host HOST --port PORT <spec.vllm_args(...)>``. Like ``ServeModels``,
    put it **last** in the pipeline (after the writer).

    ``vllm`` is the server command (default ``vllm`` on PATH, e.g. from the job image or a
    ``uv run --with vllm==...`` environment); ``gpu_memory_utilization`` and ``extra_args`` are the
    deployment's choices on top of the spec's flags. The server is ready when it answers a trial
    chat request (saturate's alive-only gate).

    ``outside_venv``: start ``vllm`` without this interpreter's virtual environment (``VIRTUAL_ENV``
    unset, its ``bin`` taken off ``PATH``), for a job image whose own Python has vLLM while the pipeline
    runs in a uv environment on top (HF Jobs); vLLM's helpers (``ninja``, ``python``) then come from the
    image."""

    type = "🔠 - LINECASTER"
    name = "🖥️ serve chat model"

    def __init__(self, spec, port: int = 8000, host: str = "127.0.0.1", gpu_memory_utilization: float | None = None,
                 extra_args: list[str] | None = None, vllm: str = "vllm", boot_timeout: int = 1800,
                 outside_venv: bool = False):
        super().__init__()
        self.spec, self.port, self.host = spec, port, host
        self.gpu_memory_utilization, self.extra_args = gpu_memory_utilization, list(extra_args or [])
        self.vllm, self.boot_timeout, self.outside_venv = vllm, boot_timeout, outside_venv

    def command(self) -> list[str]:
        """``vllm serve ...``; behind ``bash -c '<setup>; exec vllm serve ...'`` when the spec has a
        ``serve_setup`` script (run with ``VLLM`` set to the server command, ``set -euo pipefail``)."""
        cmd = [self.vllm, "serve", self.spec.model, "--host", self.host, "--port", str(self.port),
               *self.spec.vllm_args(self.gpu_memory_utilization, self.extra_args)]
        setup = getattr(self.spec, "serve_setup", lambda: None)()
        if not setup:
            return cmd
        import shlex

        return ["bash", "-c", f"set -euo pipefail\nVLLM={shlex.quote(self.vllm)}\n{setup}\nexec {shlex.join(cmd)}"]

    def launch_command(self) -> list[str]:
        """``command()``, behind ``env -u VIRTUAL_ENV PATH=...`` with ``outside_venv``."""
        cmd = self.command()
        if not self.outside_venv:
            return cmd
        import os
        import sys

        own = {os.path.realpath(os.path.join(sys.prefix, "bin"))}
        if os.environ.get("VIRTUAL_ENV"):
            own.add(os.path.realpath(os.path.join(os.environ["VIRTUAL_ENV"], "bin")))
        path = os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep) if os.path.realpath(p) not in own)
        return ["env", "-u", "VIRTUAL_ENV", f"PATH={path}", *cmd]

    def run(self, data, rank: int = 0, world_size: int = 1):
        from saturate import Engine

        with self.track_time("boot"):
            server = Engine(self.spec.model, engine="vllm", port=self.port, boot_timeout=self.boot_timeout,
                            cmd=self.launch_command())
            server.__enter__()
        try:
            yield from data
        finally:
            server.__exit__(None, None, None)
