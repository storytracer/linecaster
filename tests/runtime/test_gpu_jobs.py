"""Multi-GPU Jobs: each task of a Job gets its own server port; remote endpoints stay untouched."""
from linecaster.backends import Served
from linecaster.blocks.layout.detector import LayoutStep
from linecaster.blocks.recognition.recognizers import RecognitionStep
from linecaster.blocks.servers.serve import ServeModels
from linecaster.runtime.jobs import point_to_gpu


def test_point_to_gpu_moves_servers_and_loopback_clients():
    pipeline = [LayoutStep(Served("http://127.0.0.1:8100/v1", model="layout")),
                RecognitionStep(Served("https://example.org/v1", model="recognition")),
                ServeModels([{"name": "layout", "spec": "x:Y"}], port=8100)]
    moved = point_to_gpu(pipeline, 3)
    assert moved[0].backend.endpoint == "http://127.0.0.1:8103/v1"
    assert moved[1].backend.endpoint == "https://example.org/v1"
    assert moved[2].port == 8103
    assert pipeline[0].backend.endpoint == "http://127.0.0.1:8100/v1" and pipeline[2].port == 8100   # a copy


def test_point_to_gpu_keeps_two_servers_apart():
    from linecaster.adapters import chat_model
    from linecaster.blocks.servers.serve import ServeChatModel

    spec = chat_model("lightonai/LightOnOCR-2-1B")
    pipeline = [LayoutStep(Served("http://127.0.0.1:8100/v1", model="layout")),
                ServeModels([{"name": "layout", "spec": "x:Y"}], port=8100), ServeChatModel(spec, port=8000)]
    moved = point_to_gpu(pipeline, 2)
    assert (moved[0].backend.endpoint, moved[1].port, moved[2].port) == ("http://127.0.0.1:8102/v1", 8102, 8002)
