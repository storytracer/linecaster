"""A block that hosts models for the served blocks after it: ``linecaster serve`` starts (through
saturate's ``Engine``) when the first page arrives and stops when the task's pages are done. For a
pipeline that brings its own GPU, e.g. one HF Job per datatrove task."""
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
