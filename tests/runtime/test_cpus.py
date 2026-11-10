"""available_cpus counts what a process may use (a Ray task's CPUs, the cgroup quota, the affinity), not the
machine's CPUs; limit_threads sizes the native thread pools and keeps values already set."""
import os
import sys
import types

import pytest

from linecaster.runtime import cpus
from linecaster.runtime.cpus import THREAD_ENV, available_cpus, cgroup_cpu_quota, limit_threads


def test_cgroup_v2_quota(tmp_path):
    (tmp_path / "cpu.max").write_text("1200000 100000\n")
    assert cgroup_cpu_quota(tmp_path) == 12
    (tmp_path / "cpu.max").write_text("max 100000\n")
    assert cgroup_cpu_quota(tmp_path) is None


def test_cgroup_v1_quota(tmp_path):
    (tmp_path / "cpu").mkdir()
    (tmp_path / "cpu" / "cpu.cfs_quota_us").write_text("150000\n")
    (tmp_path / "cpu" / "cpu.cfs_period_us").write_text("100000\n")
    assert cgroup_cpu_quota(tmp_path) == 1.5
    (tmp_path / "cpu" / "cpu.cfs_quota_us").write_text("-1\n")
    assert cgroup_cpu_quota(tmp_path) is None


def test_no_cgroup(tmp_path):
    assert cgroup_cpu_quota(tmp_path / "missing") is None


def test_the_quota_caps_the_machine_count(tmp_path, monkeypatch):
    monkeypatch.setattr(cpus, "ray_task_cpus", lambda: None)
    monkeypatch.setattr(os, "sched_getaffinity", lambda pid: set(range(128)), raising=False)
    (tmp_path / "cpu.max").write_text("1200000 100000\n")
    assert available_cpus(tmp_path) == 12
    (tmp_path / "cpu.max").write_text("50000 100000\n")              # half a CPU: still one
    assert available_cpus(tmp_path) == 1
    assert available_cpus(tmp_path / "missing") == 128


def test_a_ray_task_counts_its_cpus(tmp_path, monkeypatch):
    monkeypatch.setattr(cpus, "ray_task_cpus", lambda: 2.5)
    (tmp_path / "cpu.max").write_text("1200000 100000\n")
    assert available_cpus(tmp_path) == 3


def test_ray_task_cpus_never_imports_ray(monkeypatch):
    monkeypatch.delitem(sys.modules, "ray", raising=False)
    assert cpus.ray_task_cpus() is None
    assert "ray" not in sys.modules


def test_ray_task_cpus_reads_the_assigned_resources(monkeypatch):
    context = types.SimpleNamespace(get_assigned_resources=lambda: {"CPU": 12.0, "GPU": 1.0})
    fake = types.SimpleNamespace(is_initialized=lambda: True, get_runtime_context=lambda: context)
    monkeypatch.setitem(sys.modules, "ray", fake)
    assert cpus.ray_task_cpus() == 12.0
    fake.get_runtime_context = lambda: types.SimpleNamespace(get_assigned_resources=lambda: {})   # a driver
    assert cpus.ray_task_cpus() is None


@pytest.fixture
def clean_env(monkeypatch):
    for name in THREAD_ENV:
        monkeypatch.delenv(name, raising=False)


def test_limit_threads_sets_unset_variables_and_resizes_loaded_pools(clean_env, monkeypatch):
    calls = {}
    monkeypatch.setitem(sys.modules, "cv2", types.SimpleNamespace(setNumThreads=lambda n: calls.update(cv2=n)))
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(set_num_threads=lambda n: calls.update(torch=n)))
    monkeypatch.setenv("MKL_NUM_THREADS", "2")                       # set by the user: kept
    limit_threads(12)
    assert {name: os.environ[name] for name in THREAD_ENV} == {
        "OMP_NUM_THREADS": "12", "MKL_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "12", "NUMEXPR_MAX_THREADS": "12",
        "OPENCV_FOR_THREADS_NUM": "12"}
    assert calls == {"cv2": 12, "torch": 12}


def test_limit_threads_keeps_a_pool_whose_variable_was_set(clean_env, monkeypatch):
    calls = {}
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(set_num_threads=lambda n: calls.update(torch=n)))
    monkeypatch.setenv("OMP_NUM_THREADS", "4")                       # Ray sets it for a task to its CPUs
    limit_threads(12)
    assert os.environ["OMP_NUM_THREADS"] == "4" and calls == {}
