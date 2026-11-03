"""Multi-GPU Jobs: each task of a Job gets its own server port; remote endpoints stay untouched."""
from linecaster.backends import Served
from linecaster.blocks.models import LayoutStep, RecognitionStep
from linecaster.blocks.serve import ServeModels
from linecaster.jobs import point_to_gpu


def test_point_to_gpu_moves_servers_and_loopback_clients():
    pipeline = [LayoutStep(Served("http://127.0.0.1:8100/v1", model="layout")),
                RecognitionStep(Served("https://example.org/v1", model="recognition")),
                ServeModels([{"name": "layout", "spec": "x:Y"}], port=8100)]
    moved = point_to_gpu(pipeline, 3)
    assert moved[0].backend.endpoint == "http://127.0.0.1:8103/v1"
    assert moved[1].backend.endpoint == "https://example.org/v1"
    assert moved[2].port == 8103
    assert pipeline[0].backend.endpoint == "http://127.0.0.1:8100/v1" and pipeline[2].port == 8100   # a copy
