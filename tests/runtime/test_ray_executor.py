"""RayExecutor and RayGPUExecutor: a run stops at an error that is not the pages' and fails with unfinished tasks;
each GPU task finds its GPU and moves its servers to their own port."""
import pytest

from linecaster.backends import Served
from linecaster.blocks.layout.detector import LayoutDetector
from linecaster.blocks.servers.serve import ModelServer
from linecaster.errors import PipelineConfigError
from linecaster.runtime.ray import RayGPUExecutor, assigned_gpu


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
