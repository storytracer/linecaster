"""Page engines: ``PageRecognizer`` on an in-process engine, ``ServiceServer`` (the service a page preset names),
the page pipeline script (``pipelines/transcribe_page.py``, in the describe mode) and launching a page engine's
preset. With the fake page engine and a fake service; the engines themselves are tested in their packages."""
import sys
from pathlib import Path

import pytest

from linecaster.backends import InProcess
from linecaster.blocks.base.page import page_of
from linecaster.blocks.recognition.chat import PageRecognizer
from linecaster.blocks.servers.service import ServiceServer
from linecaster.errors import PipelineConfigError, ServerError
from linecaster.pipelines import transcribe_page
from linecaster.runtime import run
from linecaster.runtime.provenance import functional_block
from linecaster.testing import check_engine, fake_service, sample_documents
from linecaster.testing.fakes import FakePageEngine

FAKE = "linecaster.testing:FakePageEngine"


def test_the_fake_page_engine_is_an_engine():
    out = check_engine(FakePageEngine)
    assert out.text == "# page\n800x400" and out.outputs[0].content == out.text and out.regions == []


def test_page_recognition_runs_a_page_engine_in_process():
    block = PageRecognizer(InProcess(FAKE, template="{width}"))
    c = block.contract()
    assert block.shape == "unit" and block.route is None and block.adapter is None
    assert {p.name for p in c.reads} == {"image"} and {p.name for p in c.adds} == {"lines", "text", "markdown"}
    docs = list(block.run(iter(sample_documents(2))))
    t = page_of(docs[0]).transcriptions["ocr_new"]
    assert docs[0].text == "800" and t.regions == [] and t.annotators[-1].engine == "fake.recognition.page.v1"
    assert "seconds" in t.annotators[-1].measurements


def test_where_an_engine_service_is_does_not_count():
    """An engine's ``endpoint`` (where its service is) is operational: the pipeline's hash leaves it out."""
    a = InProcess(FAKE, template="x")
    b = InProcess(FAKE, template="x", endpoint="http://127.0.0.1:9/")
    c = InProcess(FAKE, template="y")
    fa, fb, fc = (functional_block(PageRecognizer(x)) for x in (a, b, c))
    assert fa == fb and fa != fc


def test_a_vendor_service_from_its_preset(monkeypatch):
    s = ServiceServer("falcon-ocr@1")
    assert s.server == "vendor" and s.command() == ["/bin/bash", "/app/entrypoint_single.sh"]
    assert s.health() == ["http://127.0.0.1:8000/health", "http://127.0.0.1:5002/health"]
    monkeypatch.setenv("VIRTUAL_ENV", "/venv")
    monkeypatch.setenv("PATH", f"{Path(sys.prefix) / 'bin'}:/usr/bin")
    env = s.environment()
    assert "VIRTUAL_ENV" not in env and env["PATH"] == "/usr/bin" and env["VLLM_GPU"] == "0"
    oxr = ServiceServer("oxr-1.0@1")
    assert oxr.serve["weights_dir"] == "/models/oxr-model" and oxr.weights["revision"].startswith("c708407f")


def test_vllm_for_an_engine_package_from_its_preset():
    s = ServiceServer("surya-ocr-2.5@1", port=8011)
    cmd = s.command("/models/surya")
    assert cmd[:8] == ["vllm", "serve", "/models/surya", "--host", "127.0.0.1", "--port", "8011", "--no-enforce-eager"]
    assert cmd[-2:] == ["--served-model-name", "datalab-to/surya-ocr-2.5"]
    assert s.command()[2] == "<datalab-to/surya-ocr-2.5@00c843e9cae45611dca0a6dc2c9bbbf2dadaaed3>"
    assert s.health() == ["http://127.0.0.1:8011/health", "http://127.0.0.1:8011/v1/models"]
    with pytest.raises(PipelineConfigError, match="is a chat preset"):
        ServiceServer("lightonocr-2-1b@1")
    with pytest.raises(PipelineConfigError, match="names no service"):
        ServiceServer("indra-ocr@1")


def _service(health: str, command: list[str]) -> ServiceServer:
    s = ServiceServer("falcon-ocr@1", boot_timeout=20)
    s.serve = {**s.serve, "command": command, "health": [health]}
    return s


def test_the_service_starts_waits_for_its_health_and_stops():
    with fake_service({"GET /health": lambda body: {}}) as svc:
        s = _service(f"{svc.url}/health", [sys.executable, "-c", "import time; time.sleep(60)"])
        pages = list(s.run(iter(sample_documents(1))))
        assert len(pages) == 1 and s._proc is None and svc.requests[0][:2] == ("GET", "/health")


def test_a_service_that_exits_fails_the_task():
    s = _service("http://127.0.0.1:9/health", [sys.executable, "-c", "raise SystemExit(3)"])
    with pytest.raises(ServerError, match="exited with code 3"):
        s.warm_up()
    assert s._proc is None


def _blocks(argv):
    plan = run.describe(transcribe_page, ["IN", "OUT", *argv])
    plan.check()
    return plan.stages[0].blocks


def test_the_page_pipeline_starts_the_preset_s_service():
    blocks = _blocks(["--recognition", "falcon-ocr"])
    names = [type(b).__name__ for b in blocks]
    assert names[1] == "PageRecognizer" and names[-1] == "ServiceServer"
    rec = blocks[1]
    assert rec.backend.preset == "falcon-ocr@1" and rec.backend.spec == "linecaster_services:FalconRecognitionEngine"
    blocks = _blocks(["--recognition", "oxr-1.0", "--recognition-endpoint", "http://127.0.0.1:8123"])
    assert "ServiceServer" not in [type(b).__name__ for b in blocks]
    assert blocks[1].backend.kwargs["endpoint"] == "http://127.0.0.1:8123"
    assert "ServiceServer" not in [type(b).__name__ for b in _blocks(["--recognition", "indra-ocr"])]


def test_the_page_pipeline_takes_page_engines_only():
    with pytest.raises(PipelineConfigError, match="chat preset"):
        _blocks(["--recognition", "lightonocr-2-1b"])
    with pytest.raises(PipelineConfigError, match="does not read whole pages"):
        _blocks(["--recognition", "kraken-ppocrv6-medium"])


def test_an_engine_can_take_the_image_file_s_bytes():
    """An engine whose ``image_input`` is ``"bytes"`` (a vendor's package that decodes the file itself) gets the page
    image as the reader brought it; every other engine an RGB array."""
    from types import SimpleNamespace

    from linecaster.blocks.base.model import page_image
    from linecaster.testing import sample_png

    data = sample_png(fmt="WEBP")
    assert page_image(SimpleNamespace(image_input="bytes"), data) is data
    assert page_image(FakePageEngine(), data).shape == (400, 800, 3)
