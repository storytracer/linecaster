"""linecaster-indra: the engine's conformance (``linecaster.testing.check_engine``, with the pinned models) and its
handling of the package's page. Run in an environment with the package (README: the test command)."""
from types import SimpleNamespace

import pytest

from linecaster.engines.api import weights_of
from linecaster.testing import check_engine, sample_png
from linecaster_indra import IndraRecognitionEngine


@pytest.mark.network
def test_conformance():
    out = check_engine(IndraRecognitionEngine, options={"weights": weights_of("indra-ocr")})
    assert "species" in out.text and out.extra["raw"] == out.text and out.steps[0].revision == \
        weights_of("indra-ocr")["revision"]


class _Converter:
    """A stand-in for the package's ``Converter``: reads the file it is given and answers one page."""

    def __init__(self, page):
        self.page, self.paths = page, []

    def convert(self, path):
        from PIL import Image

        self.paths.append(path)
        self.size = Image.open(path).size
        yield 0, self.page


def _engine(page) -> IndraRecognitionEngine:
    engine = IndraRecognitionEngine()
    engine.converter, engine.version = _Converter(page), "test"
    return engine


def test_the_page_s_file_goes_through_a_temporary_file():
    page = SimpleNamespace(source="ocr", note="", markdown="# Title\nbody", blocks=[{"label": "text",
                           "bbox": [1, 2, 3, 4], "text": "body"}], rotation=0, skew=0.0)
    engine = _engine(page)
    image = sample_png(fmt="WEBP")
    out = engine(image, None)
    assert out.text == "# Title\nbody" and out.extra["blocks"][0]["bbox"] == [1.0, 2.0, 3.0, 4.0]
    assert engine.converter.size == (800, 400) and engine.converter.paths[0].endswith(".webp")   # the file as given
    import os

    assert not os.path.exists(engine.converter.paths[0])                  # removed after the read
    blank = _engine(SimpleNamespace(source="ocr", note="", markdown=None, blocks=[], rotation=0, skew=0.0))
    assert blank(image, None).text == ""


def test_a_failed_page_is_the_page_s_error():
    engine = _engine(SimpleNamespace(source="error", note="unreadable", markdown=None, blocks=[], rotation=0,
                                     skew=0.0))
    with pytest.raises(RuntimeError, match="unreadable"):
        engine(sample_png(), None)
