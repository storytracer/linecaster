"""linecaster-tesseract: the engine's conformance (``linecaster.testing.check_engine``) and its own helpers. Run in
an environment with the package (README: the test command)."""
import numpy as np
import pytest

from linecaster.engines.api import weights_of
from linecaster.testing import check_engine
from linecaster_tesseract import TesseractRecognitionEngine
from linecaster_tesseract import models as tess
from linecaster_tesseract.recognizer import crop_line


@pytest.mark.network
def test_conformance():
    out = check_engine(TesseractRecognitionEngine, options={"weights": weights_of("tessdata-best"), "lang": "eng"})
    assert [ln.reading.text for ln in out.lines][0].startswith("The species")
    assert all(w.confidence is not None for ln in out.lines for w in ln.reading.words)


def test_the_data_is_the_catalog_pin():
    td = tess.tessdata("fast")
    assert td.model == "tessdata-fast" and td.commit == weights_of("tessdata-fast")["revision"]
    assert td.repo == "tesseract-ocr/tessdata_fast" and "eng.traineddata" in td.files
    with pytest.raises(ValueError, match="comes from a GitHub repository"):
        tess.Tessdata.of({**weights_of("tessdata-fast"), "source": {"kind": "hf", "ref": "x/y"}})


def test_strict_data_accepts_only_pinned_languages(tmp_path, monkeypatch):
    monkeypatch.setenv("LINECASTER_CACHE", str(tmp_path))
    with pytest.raises(ValueError, match="is not pinned"):
        tess.tessdata_dir("klingon", "best", download=False, strict=True)
    with pytest.raises(FileNotFoundError):                   # not in this (empty) cache, and no download
        tess.tessdata_dir("eng", "best", download=False)


def test_a_line_crop_is_white_outside_the_polygon():
    image = np.zeros((50, 100), dtype=np.uint8)
    crop, dx, dy = crop_line(image, [[10, 10], [60, 10], [60, 20], [10, 20]], pad=2)
    assert (dx, dy) == (8, 8) and crop.shape == (14, 54) and crop[0, 0] == 255 and crop[5, 5] == 0
