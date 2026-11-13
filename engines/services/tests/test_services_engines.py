"""linecaster-services: the engines' conformance (``linecaster.testing.check_engine``) and their requests and answers,
against a fake service (``linecaster.testing.fake_service``). Run in an environment with the package (README: the
test command)."""
import base64
import io

import numpy as np
import pytest
from PIL import Image

from linecaster.testing import check_engine, fake_service, sample_page
from linecaster_services import FalconRecognitionEngine, OxrRecognitionEngine
from linecaster_services.http import ServiceError, multipart


def _size_of_data_uri(uri: str) -> tuple[int, int]:
    assert uri.startswith("data:image/jpeg;base64,")
    return Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))).size


def _falcon(body):
    w, h = _size_of_data_uri(body["images"][0])
    return {"markdown_result": f"# page\n{w}x{h}", "json_result": [{"label": "text"}], "total_output_tokens": 7,
            "processing_time_ms": 12}


def test_falcon_conformance_and_request():
    with fake_service({"GET /health": lambda b: {}, "POST /falconocr/parse": _falcon}) as svc:
        out = check_engine(FalconRecognitionEngine, options={"endpoint": svc.url})
        assert out.text == "# page\n800x400" and out.outputs[0].content == out.text
        assert out.falcon__regions_json == [{"label": "text"}] and out.falcon__processing_ms == 12
        assert out.annotators[0].measurements["completion_tokens"] == 7 == out.outputs[0].completion_tokens
        _, path, body = svc.requests[-1]
        assert path == "/falconocr/parse" and body["skip_layout"] is False
        engine = FalconRecognitionEngine(endpoint=svc.url)
        big = np.asarray(sample_page(3000, 1000).convert("RGB"))
        assert _size_of_data_uri(engine.request(big)["images"][0]) == (2048, 683)    # scaled down, never up


def test_falcon_without_markdown_is_the_page_s_error():
    with pytest.raises(ServiceError, match="without markdown_result"):
        FalconRecognitionEngine().parse({"error": "x"})
    with pytest.raises(ConnectionError, match="does not answer /health"):
        FalconRecognitionEngine(endpoint="http://127.0.0.1:9").load()


def _oxr(form):
    name, data = form["file"]
    w, h = Image.open(io.BytesIO(data)).size
    return {"code": 0, "data": {"result": {"outputs": {"markdown": f"page {w}x{h}\n![](imgs/a.png)",
                                                       "json": [{"type": "text"}]}},
                                "metadata": {"processing_time_ms": 5}}, "warnings": []}


def test_oxr_conformance_and_request():
    with fake_service({"GET /docs": lambda b: {}, "POST /v1/parse/sync": _oxr}) as svc:
        out = check_engine(OxrRecognitionEngine, options={"endpoint": svc.url})
        assert out.text == "page 800x400\n![](imgs/a.png)" and out.oxr__blocks_json == [{"type": "text"}]
        assert out.outputs[0].content == out.text and out.oxr__warnings == [] and out.oxr__processing_ms == 5
        _, path, form = svc.requests[-1]
        assert path == "/v1/parse/sync" and form["api_key"] == "dummy"
        assert form["output_formats"] == ["markdown", "json"]                 # one field per format
        filename, data = form["file"]
        page = np.asarray(sample_page().convert("RGB"))
        assert filename == "page.png" and np.array_equal(np.asarray(Image.open(io.BytesIO(data))), page)   # lossless


def test_oxr_failures_are_the_page_s_error():
    with pytest.raises(ServiceError, match="code=3"):
        OxrRecognitionEngine().parse({"code": 3, "message": "boom", "data": {}})
    with pytest.raises(ServiceError, match="without markdown"):
        OxrRecognitionEngine().parse({"code": 0, "data": {"result": {"outputs": {}}}})


def test_a_list_field_is_one_field_per_item():
    data, kind = multipart({"a": ["x", "y"], "b": 1}, {"f": ("p.png", b"\x89PNG", "image/png")})
    assert kind.startswith("multipart/form-data; boundary=")
    assert data.count(b'name="a"') == 2 and b'name="b"\r\n\r\n1\r\n' in data and b'filename="p.png"' in data
