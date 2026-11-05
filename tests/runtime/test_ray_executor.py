"""RayGPUExecutor: each task finds its GPU and moves its servers to their own port."""
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
