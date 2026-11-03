"""A block that hosts models for a task's served blocks: ``linecaster serve`` starts (through saturate's
``Engine``) when the task starts and stops when all its pages are through. For a pipeline that brings
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
