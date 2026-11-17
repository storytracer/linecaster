"""The CPUs a process may use, and the thread pools sized to them.

``os.cpu_count()`` is the machine's count: in a Kubernetes pod, a Ray task or a container with a CPU limit it is
often many times what the process may use, and thread pools sized by it oversubscribe the CPUs they get (a pod with
a CPU limit is then throttled). ``available_cpus`` is the count to size by instead: a Ray task's or actor's CPUs,
else the cgroup's CPU quota, else the CPUs the process may run on. ``limit_threads`` sizes the common native thread
pools (OpenMP, BLAS, OpenCV, torch) to a count; a value already set in the environment is kept.
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

#: the environment variables that size native thread pools, read when a library loads (and by the servers a task
#: starts, which inherit the environment)
THREAD_ENV = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_MAX_THREADS",
              "OPENCV_FOR_THREADS_NUM")


def available_cpus(cgroup: str | Path = "/sys/fs/cgroup") -> int:
    """Returns the number of CPUs this process may use, at least 1.

    A Ray task's or actor's assigned CPUs (rounded up) when the process is one; otherwise the CPUs the process may run
    on (its affinity, else ``os.cpu_count()``), capped by the cgroup's CPU quota (cgroup v2 ``cpu.max``, v1
    ``cpu.cfs_quota_us``), rounded down.

    Args:
        cgroup: the cgroup file system's mount point, the default for Linux; elsewhere no quota is found.
    """
    ray_cpus = ray_task_cpus()
    if ray_cpus:
        return max(1, math.ceil(ray_cpus))
    try:
        n = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):              # macOS has no affinity
        n = os.cpu_count() or 1
    quota = cgroup_cpu_quota(cgroup)
    if quota is not None:
        n = min(n, math.floor(quota))
    return max(1, n)


def ray_task_cpus() -> float | None:
    """Returns the CPUs Ray assigned to this process if it is a Ray task or actor, else None (also on a driver)."""
    if "ray" not in sys.modules:                   # never imports Ray: a process that has not is no Ray worker
        return None
    import ray

    try:
        if not ray.is_initialized():
            return None
        cpus = ray.get_runtime_context().get_assigned_resources().get("CPU")
    except Exception:                              # a driver, or a Ray without the runtime context's resources
        return None
    return float(cpus) if cpus else None


def cgroup_cpu_quota(cgroup: str | Path = "/sys/fs/cgroup") -> float | None:
    """Returns the cgroup's CPU quota in CPUs (``1.5`` for 150 ms per 100 ms), or None if there is none.

    Args:
        cgroup: the cgroup file system's mount point: ``cpu.max`` there (v2), else ``cpu/cpu.cfs_quota_us`` and
            ``cpu/cpu.cfs_period_us`` (v1).
    """
    root = Path(cgroup)
    try:
        quota, period = (root / "cpu.max").read_text().split()[:2]
        return None if quota == "max" else int(quota) / int(period)
    except (OSError, ValueError):
        pass
    try:
        quota = int((root / "cpu" / "cpu.cfs_quota_us").read_text())
        period = int((root / "cpu" / "cpu.cfs_period_us").read_text())
    except (OSError, ValueError):
        return None
    return None if quota <= 0 or period <= 0 else quota / period


def limit_threads(n: int) -> None:
    """Sizes the native thread pools to ``n`` threads, keeping values already set in the environment.

    Sets ``THREAD_ENV`` where unset (libraries loaded later, and the servers this process starts, read them), and
    resizes OpenCV's and torch's pools if they are loaded already, unless their variable was set.

    Args:
        n: the threads per pool, at least 1.
    """
    n = max(1, int(n))
    given = {name for name in THREAD_ENV if name in os.environ}
    for name in THREAD_ENV:
        os.environ.setdefault(name, str(n))
    if "cv2" in sys.modules and "OPENCV_FOR_THREADS_NUM" not in given:
        sys.modules["cv2"].setNumThreads(n)
    if "torch" in sys.modules and "OMP_NUM_THREADS" not in given:
        sys.modules["torch"].set_num_threads(n)
