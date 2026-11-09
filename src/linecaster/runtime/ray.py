"""Ray for linecaster pipelines.

``RayExecutor`` is datatrove's ``RayPipelineExecutor`` that stops as a local run does (``LocalExecutor``): an error
that is not the pages' (``NOT_THE_PAGES``: the configuration, the catalog, a server: a host's ``stop_on``, no proxy
left, a pause beyond ``max_pause``; a 429 only pauses the worker that got it, ``linecaster.net.http.Pause``) in one
task stops the whole run, where datatrove only ends that task and starts the next one (whose first request would go
straight into the block that stopped the first). The task writes a stop marker to the logging folder
(``STOP_MARKER``, as datatrove marks finished tasks), every task after it finds the marker and ends before its
pipeline starts, and the launch then fails with the first task's error. A launch with tasks that did not finish fails
too (they run again on the next launch), so a Ray job that left work undone does not end as succeeded. A new launch
removes the marker. Each task's process starts its search for a worker slot in the broker at its rank modulo the
tasks running at once (``linecaster.broker.set_worker_index``), so tasks started together claim different slots.

``RayGPUExecutor`` is ``RayExecutor`` with one GPU per task. Ray restricts each task to its GPU through
``CUDA_VISIBLE_DEVICES``. Several tasks share a machine, so each task moves the servers its pipeline starts
(``ModelServer``, ``ChatModelServer``) and their loopback clients up by its GPU index
(``linecaster.runtime.jobs.point_to_gpu``). Ray itself is the ``ray`` extra.
"""
from __future__ import annotations

import json
import os
import sys
import time

from datatrove.executor.ray import RayPipelineExecutor

from ..errors import LinecasterError, PipelineConfigError
from .jobs import point_to_gpu

#: the marker a task writes to the logging folder when the run must stop
STOP_MARKER = "stopped.json"


def assigned_gpu() -> int:
    """The index of the GPU Ray gave this task: the first entry of ``CUDA_VISIBLE_DEVICES``."""
    value = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    first = value.split(",")[0].strip()
    if not first.isdigit():
        raise PipelineConfigError(f"no GPU index for this task (CUDA_VISIBLE_DEVICES={value!r}); run with gpus_per_task=1")
    return int(first)


def hand_over() -> None:
    """The task's process ends: its fetchers are closed and its worker slot in the broker handed over, so the next
    process on this machine is the same worker and goes on with its proxies (``linecaster.broker``)."""
    if "linecaster.net.http" in sys.modules:
        from ..net.http import close_shared

        close_shared()


class RayExecutor(RayPipelineExecutor):
    """``RayPipelineExecutor`` whose run stops at an error that is not the pages' and fails when tasks did not
    finish (see the module docstring). Takes ``RayPipelineExecutor``'s arguments."""

    def run(self):
        self._clear_stop()
        super().run()
        stop = self.stopped()
        if stop is not None:
            raise LinecasterError(f"the run stopped: task {stop['rank'] + 1:,}/{self.world_size:,} had "
                                  f"{stop['type']}: {stop['error']}; the other unfinished tasks run on the next "
                                  "launch")
        unfinished = len(self.get_incomplete_ranks(range(self.world_size)))
        if unfinished:
            raise LinecasterError(f"{unfinished:,} of {self.world_size:,} tasks did not finish (their errors are in "
                                  "the logging folder's task logs); they run again on the next launch")

    def _run_for_rank(self, rank: int, local_rank: int = 0, node_rank: int = -1):
        from ..blocks.base.page import NOT_THE_PAGES

        from ..broker import set_worker_index

        at_once = max(1, self.workers * self.tasks_per_job)            # tasks at once: distinct ranks, distinct slots
        set_worker_index(rank % at_once, at_once)
        stop = self.stopped()
        if stop is not None:                         # the run stops: this task ends before its pipeline starts
            raise LinecasterError(f"task {rank + 1:,} not started: the run stopped at task {stop['rank'] + 1:,} "
                                  f"({stop['type']})")
        try:
            return super()._run_for_rank(rank, local_rank, node_rank)
        except NOT_THE_PAGES as e:
            if self.stopped() is None:
                self._mark_stop(rank, e)
            raise
        finally:
            hand_over()

    def stopped(self) -> dict | None:
        """The stop marker (``rank``, ``type``, ``error``, ``time``) if a task stopped the run, else None."""
        try:
            with self.logging_dir.open(STOP_MARKER, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return None

    def _mark_stop(self, rank: int, error: BaseException) -> None:
        first = str(error).splitlines()[0] if str(error) else ""
        with self.logging_dir.open(STOP_MARKER, "w") as f:
            json.dump({"rank": rank, "type": type(error).__name__, "error": first, "time": time.time()}, f)

    def _clear_stop(self) -> None:
        if self.logging_dir.exists(STOP_MARKER):
            self.logging_dir.rm(STOP_MARKER)


class RayGPUExecutor(RayExecutor):
    """``RayExecutor`` for pipelines with a server block: one task per GPU, each task's servers on their own ports
    (``point_to_gpu``). Takes ``RayPipelineExecutor``'s arguments."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("gpus_per_task", 1)
        super().__init__(*args, **kwargs)
        if self.gpus_per_task != 1:
            raise PipelineConfigError("RayGPUExecutor runs one task per GPU (gpus_per_task=1)")

    def _run_for_rank(self, rank: int, local_rank: int = 0, node_rank: int = -1):
        self.pipeline = point_to_gpu(self.pipeline, assigned_gpu())
        return super()._run_for_rank(rank, local_rank, node_rank)
