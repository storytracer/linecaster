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

Before it submits a task, a launch checks that the cluster can run one: a live node with the CPUs, the memory and
the GPU a task reserves (``cpus_per_task``; ``mem_per_task_gb``, else ``mem_per_cpu_gb`` per CPU; one GPU on
``RayGPUExecutor``). Ray would keep such a task waiting without an error. It logs how many tasks fit at once, and
warns when fewer than the run's tasks at once do. ``check_fit=False`` leaves the check out, for a cluster that adds
nodes on demand. Each task sizes the native thread pools to its CPUs (``linecaster.runtime.cpus.limit_threads``), not
to the machine's.

``RayGPUExecutor`` is ``RayExecutor`` with one GPU per task. Ray restricts each task to its GPU through
``CUDA_VISIBLE_DEVICES``. Several tasks share a machine, so each task moves the servers its pipeline starts
(``ModelServer``, ``ChatModelServer``) and their loopback clients up by its GPU index
(``linecaster.runtime.jobs.point_to_gpu``). Ray itself is the ``ray`` extra.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

from datatrove.executor.ray import RayPipelineExecutor
from loguru import logger

from ..errors import LinecasterError, PipelineConfigError
from .cpus import available_cpus, limit_threads
from .jobs import point_to_gpu

#: the marker a task writes to the logging folder when the run must stop
STOP_MARKER = "stopped.json"

GIB = 1024 ** 3


def task_resources(cpus_per_task: float, mem_per_cpu_gb: float, gpus_per_task: float) -> dict[str, float]:
    """Returns what one task reserves on a Ray node, as datatrove's ``RayPipelineExecutor`` asks for it: ``CPU``,
    ``memory`` (bytes, ``mem_per_cpu_gb`` GiB per CPU) and ``GPU``.

    Args:
        cpus_per_task, mem_per_cpu_gb, gpus_per_task: the executor's reservation.
    """
    return {"CPU": cpus_per_task, "memory": int(mem_per_cpu_gb * cpus_per_task * GIB), "GPU": gpus_per_task}


def tasks_on_node(resources: dict[str, float], need: dict[str, float]) -> int:
    """Returns how many tasks reserving ``need`` fit on a node with ``resources`` (Ray's total resources of a node).

    Args:
        resources: the node's resources (``CPU``, ``memory`` in bytes, ``GPU``; a missing one is 0).
        need: one task's reservation (``task_resources``); a resource it reserves 0 of does not limit.
    """
    counts = [math.floor(resources.get(name, 0) / amount + 1e-9) for name, amount in need.items() if amount > 0]
    return max(0, min(counts)) if counts else 0


def describe_resources(r: dict[str, float]) -> str:
    """Returns a reservation or a node's resources in words: ``12 CPUs, 48 GiB, 1 GPU``.

    Args:
        r: ``CPU``, ``memory`` (bytes) and ``GPU``; a missing one counts as 0.
    """
    def n(x: float) -> str:
        return f"{x:g}"

    cpus, gpus = r.get("CPU", 0), r.get("GPU", 0)
    return (f"{n(cpus)} CPU{'' if cpus == 1 else 's'}, {n(round(r.get('memory', 0) / GIB, 1))} GiB, "
            f"{n(gpus)} GPU{'' if gpus == 1 else 's'}")


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
    finish, and that checks first that the cluster can run a task (see the module docstring).

    Args:
        *args, **kwargs: ``RayPipelineExecutor``'s arguments.
        mem_per_task_gb: the memory a task reserves in GiB, whatever its CPUs; default None: ``mem_per_cpu_gb`` per
            CPU, as datatrove reserves it.
        check_fit: whether a launch first checks that a live node can run a task; default True.
    """

    def __init__(self, *args, mem_per_task_gb: float | None = None, check_fit: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.mem_per_task_gb = mem_per_task_gb
        self.check_fit = check_fit
        if mem_per_task_gb is not None:
            if mem_per_task_gb <= 0:
                raise PipelineConfigError(f"mem_per_task_gb must be positive, not {mem_per_task_gb}")
            self.mem_per_cpu_gb = mem_per_task_gb / max(self.cpus_per_task, 1)   # datatrove reserves per CPU

    def run(self):
        if self.check_fit:
            import ray

            if ray.is_initialized():
                self.check_cluster(ray.nodes())
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

    def check_cluster(self, nodes: list[dict]) -> int:
        """Returns how many tasks fit on the live ``nodes`` at once; raises ``PipelineConfigError`` if none fits.

        Logs the count, as a warning when it is below the run's tasks at once (``workers``, at most ``tasks``).

        Args:
            nodes: ``ray.nodes()``: each node's ``Alive`` and ``Resources``.
        """
        need = task_resources(self.cpus_per_task, self.mem_per_cpu_gb, self.gpus_per_task)
        alive = [n.get("Resources", {}) for n in nodes if n.get("Alive")]
        fits = [tasks_on_node(r, need) for r in alive]
        if not any(fits):
            most = {name: max((r.get(name, 0) for r in alive), default=0) for name in need}
            raise PipelineConfigError(
                f"no Ray node can run a task: a task reserves {describe_resources(need)} (--cpus-per-task, "
                f"--mem-per-cpu-gb or --mem-per-task-gb, one GPU for a stage with models), and "
                f"{'the live node has' if len(alive) == 1 else f'the {len(alive):,} live nodes have at most'} "
                f"{describe_resources(most)}{'' if len(alive) == 1 else ' each'}. Start the workers with enough "
                "(ray start --num-cpus, --memory, --num-gpus), reserve less per task, or pass --no-fit-check for a "
                "cluster that adds nodes on demand")
        at_once, wanted = sum(fits), min(self.workers, self.tasks)
        log = logger.warning if at_once < wanted else logger.info
        log("Ray: {at_once} tasks fit at once on {nodes} nodes ({need} each); the run has {wanted} at once",
            at_once=at_once, nodes=sum(1 for f in fits if f), need=describe_resources(need), wanted=wanted)
        return at_once

    def _run_for_rank(self, rank: int, local_rank: int = 0, node_rank: int = -1):
        from ..blocks.base.page import NOT_THE_PAGES

        from ..broker import set_worker_index

        limit_threads(available_cpus())                 # the task's CPUs, not the machine's
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
