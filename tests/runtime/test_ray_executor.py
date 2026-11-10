"""RayExecutor and RayGPUExecutor: a run stops at an error that is not the pages' and fails with unfinished tasks;
each GPU task finds its GPU and moves its servers to their own port; a launch checks that a node can run a task, and
a task sizes its thread pools to its CPUs."""
import pytest

from linecaster.backends import Served
from linecaster.blocks.layout.detector import LayoutDetector
from linecaster.blocks.servers.serve import ModelServer
from linecaster.errors import PipelineConfigError
from linecaster.runtime.ray import GIB, RayExecutor, RayGPUExecutor, assigned_gpu, task_resources, tasks_on_node


@pytest.fixture(autouse=True)
def threads(monkeypatch):
    """The thread limits each task sets, recorded instead of set in this process's environment."""
    seen = []
    monkeypatch.setattr("linecaster.runtime.ray.limit_threads", seen.append)
    monkeypatch.setattr("linecaster.runtime.ray.available_cpus", lambda: 12)
    return seen


def node(cpus, mem_gib, gpus=0, alive=True):
    """A node as ``ray.nodes()`` lists it."""
    resources = {"CPU": cpus, "memory": mem_gib * GIB, **({"GPU": gpus} if gpus else {})}
    return {"Alive": alive, "Resources": resources}


def test_tasks_on_node():
    need = task_resources(12, 4, 1)                                   # 12 CPUs, 48 GiB, 1 GPU
    assert need == {"CPU": 12, "memory": 48 * GIB, "GPU": 1}
    assert tasks_on_node(node(96, 576, 8)["Resources"], need) == 8
    assert tasks_on_node(node(4, 60, 1)["Resources"], need) == 0     # the CPUs limit
    assert tasks_on_node(node(96, 576)["Resources"], need) == 0      # no GPU
    assert tasks_on_node(node(24, 200)["Resources"], task_resources(12, 4, 0)) == 2   # a CPU task: no GPU needed


def test_a_launch_fails_when_no_node_can_run_a_task(tmp_path):
    """Workers started with 4 CPUs each and the default reservation of 12: Ray would keep every task waiting."""
    ex = RayGPUExecutor([], tasks=64, cpus_per_task=12, mem_per_cpu_gb=4, logging_dir=str(tmp_path))
    nodes = [node(0, 16)] + [node(4, 60, 1) for _ in range(64)] + [node(96, 576, 8, alive=False)]
    with pytest.raises(PipelineConfigError, match=r"a task reserves 12 CPUs, 48 GiB, 1 GPU .* the 65 live nodes "
                                                   r"have at most 4 CPUs, 60 GiB, 1 GPU each"):
        ex.check_cluster(nodes)


def test_a_launch_counts_the_tasks_that_fit_at_once(tmp_path):
    ex = RayGPUExecutor([], tasks=64, cpus_per_task=12, mem_per_cpu_gb=4, logging_dir=str(tmp_path))
    assert ex.check_cluster([node(0, 16)] + [node(12, 72, 1) for _ in range(64)]) == 64
    assert ex.check_cluster([node(96, 576, 8), node(12, 72, 1)]) == 9   # fewer than the run's 64: a warning


def test_the_check_runs_before_the_tasks(tmp_path, monkeypatch):
    import ray

    ex = RayGPUExecutor([], tasks=1, cpus_per_task=12, logging_dir=str(tmp_path))
    monkeypatch.setattr(ray, "is_initialized", lambda: True)
    monkeypatch.setattr(ray, "nodes", lambda: [node(4, 60, 1)])
    launched = []
    monkeypatch.setattr("datatrove.executor.ray.RayPipelineExecutor.run", lambda self: launched.append(self))
    with pytest.raises(PipelineConfigError, match="no Ray node can run a task"):
        ex.run()
    assert launched == []
    unchecked = RayGPUExecutor([], tasks=1, cpus_per_task=12, check_fit=False, logging_dir=str(tmp_path))
    unchecked.mark_rank_as_completed(0)                               # the launch then succeeds
    unchecked.run()
    assert len(launched) == 1                                         # --no-fit-check: launched as before


def test_mem_per_task_gb_reserves_memory_whatever_the_cpus(tmp_path):
    ex = RayExecutor([], tasks=1, cpus_per_task=8, mem_per_task_gb=48, logging_dir=str(tmp_path))
    assert task_resources(ex.cpus_per_task, ex.mem_per_cpu_gb, ex.gpus_per_task)["memory"] == 48 * GIB
    assert RayExecutor([], tasks=1, cpus_per_task=8, mem_per_cpu_gb=4, logging_dir=str(tmp_path)).mem_per_cpu_gb == 4
    with pytest.raises(PipelineConfigError):
        RayExecutor([], tasks=1, mem_per_task_gb=0, logging_dir=str(tmp_path))


def test_the_command_line_passes_the_reservation_on(tmp_path):
    from linecaster.runtime import run

    ap = run.parser(None)
    a = ap.parse_args(["in/", str(tmp_path / "out"), "--on", "ray", "--cpus-per-task", "8", "--mem-per-task-gb",
                       "48", "--no-fit-check"])
    assert (a.cpus_per_task, a.mem_per_task_gb, a.fit_check) == (8, 48, False)
    assert ap.parse_args(["in/", "out/"]).fit_check is True


def test_a_task_sizes_its_threads_to_its_cpus(tmp_path, monkeypatch, threads):
    monkeypatch.setattr("datatrove.executor.ray.RayPipelineExecutor._run_for_rank",
                        lambda self, rank, local_rank=0, node_rank=-1: None)
    RayExecutor([], tasks=1, logging_dir=str(tmp_path / "logs"))._run_for_rank(0)
    assert threads == [12]


def test_assigned_gpu(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "5")
    assert assigned_gpu() == 5
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    with pytest.raises(PipelineConfigError):
        assigned_gpu()


def test_task_moves_to_its_gpu_port(monkeypatch, tmp_path):
    pipeline = [LayoutDetector(Served("http://127.0.0.1:8100/v1", model="layout")),
                ModelServer([{"name": "layout", "spec": "x:Y"}], port=8100)]
    ex = RayGPUExecutor(pipeline, tasks=2, logging_dir=str(tmp_path / "logs"))
    seen = {}
    monkeypatch.setattr("datatrove.executor.ray.RayPipelineExecutor._run_for_rank",
                        lambda self, rank, local_rank=0, node_rank=-1: seen.update(
                            endpoint=self.pipeline[0].backend.endpoint, port=self.pipeline[1].port))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "3")
    ex._run_for_rank(0)
    assert seen == {"endpoint": "http://127.0.0.1:8103/v1", "port": 8103}
    assert ex.gpus_per_task == 1


def test_one_gpu_per_task(tmp_path):
    with pytest.raises(PipelineConfigError):
        RayGPUExecutor([], tasks=1, gpus_per_task=2, logging_dir=str(tmp_path))


def test_connect_ray_joins_the_given_cluster_once(monkeypatch):
    import ray

    from linecaster.runtime import run

    calls = []
    monkeypatch.setattr(ray, "is_initialized", lambda: bool(calls))
    monkeypatch.setattr(ray, "init", lambda address: calls.append(address))
    run.connect_ray("ray-head:6379")
    run.connect_ray("ray-head:6379")
    assert calls == ["ray-head:6379"]


def _stop_executor(tmp_path, monkeypatch, outcome):
    """A RayExecutor whose pipeline run is ``outcome`` (a value to return or an exception to raise)."""
    from linecaster.runtime.ray import RayExecutor

    calls = []

    def run_for_rank(self, rank, local_rank=0, node_rank=-1):
        calls.append(rank)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr("datatrove.executor.ray.RayPipelineExecutor._run_for_rank", run_for_rank)
    return RayExecutor([], tasks=3, logging_dir=str(tmp_path / "logs")), calls


def test_an_error_that_is_not_the_pages_stops_every_later_task(tmp_path, monkeypatch):
    """A host's stop_on (StopRequests, a ServerError) in one task: the stop marker, and the next task ends before its
    pipeline starts, so no request of it reaches the host."""
    from linecaster.errors import LinecasterError, ServerError

    ex, calls = _stop_executor(tmp_path, monkeypatch,
                               ServerError("HTTP 403 from www.loc.gov: its policy stops the run"))
    with pytest.raises(ServerError):
        ex._run_for_rank(0)
    assert ex.stopped()["rank"] == 0 and ex.stopped()["type"] == "ServerError" and "403" in ex.stopped()["error"]
    with pytest.raises(LinecasterError, match="task 2 not started: the run stopped at task 1"):
        ex._run_for_rank(1)
    assert calls == [0]                                   # the second task's pipeline never ran


def test_a_page_error_does_not_stop_the_run(tmp_path, monkeypatch):
    from linecaster.errors import PageError

    ex, _ = _stop_executor(tmp_path, monkeypatch, PageError("p1", message="too many failed pages"))
    with pytest.raises(PageError):
        ex._run_for_rank(0)
    assert ex.stopped() is None


def test_a_launch_fails_when_the_run_stopped_or_tasks_did_not_finish(tmp_path, monkeypatch):
    from linecaster.errors import LinecasterError, ServerError

    ex, _ = _stop_executor(tmp_path, monkeypatch, ServerError("HTTP 403 from www.loc.gov"))

    def launch(self):                                     # one task stops the run, as on the cluster
        with pytest.raises(ServerError):
            self._run_for_rank(1)

    monkeypatch.setattr("datatrove.executor.ray.RayPipelineExecutor.run", launch)
    with pytest.raises(LinecasterError, match=r"the run stopped: task 2/3 had ServerError: HTTP 403"):
        ex.run()
    monkeypatch.setattr("datatrove.executor.ray.RayPipelineExecutor.run", lambda self: None)
    with pytest.raises(LinecasterError, match="3 of 3 tasks did not finish"):
        ex.run()                                          # the marker is gone (a new launch), the tasks are not done
    assert ex.stopped() is None
    for rank in range(3):
        ex.mark_rank_as_completed(rank)
    ex.run()                                              # every task finished: the launch succeeds
