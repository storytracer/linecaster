"""``Pipeline`` and ``from_dict``: a pipeline checks, runs and goes to plain data and back."""
import json

import pytest

from linecaster import Component, Pipeline
from linecaster.backends import InProcess, Served, backend_from_dict
from linecaster.components.lines import LineAssigner, LineDetector
from linecaster.components.readers import ImageFolderReader
from linecaster.components.recognition import LineRecognizer
from linecaster.components.servers import EngineServer
from linecaster.components.writers import PageJsonlWriter
from linecaster.core.page import page_of
from linecaster.errors import PipelineConfigError
from linecaster.secrets import EnvVar
from linecaster.testing import sample_documents

LINES, TEXT = "linecaster.testing:FakeLineEngine", "linecaster.testing:FakeRecognitionEngine"


def _pipeline() -> Pipeline:
    return Pipeline([LineDetector(InProcess(LINES)), LineRecognizer(InProcess(TEXT, template="line {index}"))])


def test_a_pipeline_checks_runs_and_draws():
    pipeline = _pipeline()
    assert len(pipeline) == 2 and repr(pipeline) == "Pipeline([LineDetector, LineRecognizer])"
    out = pipeline.run_pages(sample_documents(2, text=False))
    assert page_of(out[0]).transcriptions["ocr_new"].text.startswith("line 0\n")
    whole = Pipeline([ImageFolderReader("scans/"), *pipeline.components, PageJsonlWriter("out/pages")])
    assert whole.check().problems == [] and "LineRecognizer" in whole.draw()
    with pytest.raises(PipelineConfigError, match="reads"):
        Pipeline([ImageFolderReader("scans/"), LineRecognizer(InProcess(TEXT))]).check()        # no lines to read


def test_a_pipeline_puts_its_servers_last():
    server = EngineServer([])
    pipeline = Pipeline([LineDetector(Served("http://127.0.0.1:8100/v1", model="lines")), LineAssigner()], servers=[server])
    assert pipeline.steps()[-1] is server and pipeline.to_dict()["servers"][0]["component"] == "EngineServer"


def test_a_pipeline_goes_to_plain_data_and_back():
    data = json.loads(json.dumps(_pipeline().to_dict()))
    again = Pipeline.from_dict(data)
    assert again.to_dict() == data and [type(c) for c in again.components] == [LineDetector, LineRecognizer]
    out = again.run_pages(sample_documents(1, text=False))
    assert page_of(out[0]).transcriptions["ocr_new"].text.startswith("line 0")


def test_backends_come_back_with_their_secrets_by_name():
    served = Served("https://api.example.org/v1", model="m", api_key=EnvVar("LC_TEST_KEY"), headers={"X-Team": "ocr"})
    again = backend_from_dict(json.loads(json.dumps(served.to_dict())))
    assert again.to_dict() == served.to_dict() and again.api_key == EnvVar("LC_TEST_KEY")
    with pytest.raises(PipelineConfigError, match="unknown backend"):
        backend_from_dict({"backend": "elsewhere"})
