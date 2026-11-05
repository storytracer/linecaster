"""Ray for linecaster pipelines that start their model servers inside the tasks.

``RayGPUExecutor`` is datatrove's ``RayPipelineExecutor`` with one GPU per task. Ray restricts each task
to its GPU through ``CUDA_VISIBLE_DEVICES``. Several tasks share a machine, so each task moves the servers
its pipeline starts (``ServeModels``, ``ServeChatModel``) and their loopback clients up by its GPU
index (``linecaster.runtime.jobs.point_to_gpu``). Ray itself is the ``ray`` extra.
"""
from __future__ import annotations

import os

from datatrove.executor.ray import RayPipelineExecutor

from .jobs import point_to_gpu


def assigned_gpu() -> int:
    """The index of the GPU Ray gave this task: the first entry of ``CUDA_VISIBLE_DEVICES``."""
    value = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    first = value.split(",")[0].strip()
    if not first.isdigit():
        raise RuntimeError(f"no GPU index for this task (CUDA_VISIBLE_DEVICES={value!r}); run with gpus_per_task=1")
    return int(first)


class RayGPUExecutor(RayPipelineExecutor):
    """``RayPipelineExecutor`` for pipelines with a server block: one task per GPU, each task's servers on
    their own ports (``point_to_gpu``). Takes ``RayPipelineExecutor``'s arguments."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("gpus_per_task", 1)
        super().__init__(*args, **kwargs)
        if self.gpus_per_task != 1:
            raise ValueError("RayGPUExecutor runs one task per GPU (gpus_per_task=1)")

    def _run_for_rank(self, rank: int, local_rank: int = 0, node_rank: int = -1):
        self.pipeline = point_to_gpu(self.pipeline, assigned_gpu())
        return super()._run_for_rank(rank, local_rank, node_rank)
