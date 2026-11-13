"""linecaster-kraken: the engine's conformance (``linecaster.testing.check_engine``, on the CPU and on CUDA) and
its own helpers. Run in an environment with the package (README: the test command)."""
from types import SimpleNamespace

import pytest

from linecaster.data import Line
from linecaster.engines.api import weights_of
from linecaster.testing import check_engine, sample_layout
from linecaster_kraken import KrakenRecognitionEngine
from linecaster_kraken.models import MODEL_IDS, SIZES
from linecaster_kraken.recognizer import max_bbox, mean_confidence, record_words
from linecaster_kraken.segmentation import line_record, lines_to_segmentation


@pytest.mark.network
def test_conformance_on_the_cpu():
    out = check_engine(KrakenRecognitionEngine, options={"weights": weights_of("kraken-ppocrv6-tiny"),
                                                         "model": "tiny", "device": "cpu"})
    assert all(ln.reading.text for ln in out.lines) and all(ln.reading.words for ln in out.lines)
    assert out.annotators[-1].revision == weights_of("kraken-ppocrv6-tiny")["revision"]


@pytest.mark.gpu
@pytest.mark.network
def test_conformance_on_cuda():
    out = check_engine(KrakenRecognitionEngine, options={"weights": weights_of("kraken-ppocrv6-medium")})
    assert "cuda" in out.annotators[-1].backend and out.annotators[-1].settings["precision"] == "bf16-mixed"


def test_sizes_name_their_catalog_models():
    assert {s: weights_of(MODEL_IDS[s])["model"] for s in SIZES} == {s: f"kraken-ppocrv6-{s}" for s in SIZES}
    with pytest.raises(ValueError, match="does not name the pinned weights"):
        KrakenRecognitionEngine(model="small", weights=weights_of("kraken-ppocrv6-tiny"))


def test_words_follow_kraken_s_serializer():
    rec = SimpleNamespace(prediction="ab  c", cuts=[[[0, 0], [2, 0], [2, 4], [0, 4]], [[2, 0], [4, 0], [4, 4], [2, 4]],
                                                     [[4, 0], [5, 0], [5, 4], [4, 4]], [[5, 0], [6, 0], [6, 4], [5, 4]],
                                                     [[6, 0], [9, 0], [9, 5], [6, 5]]],
                          confidences=[0.5, 1.0, 0.9, 0.9, 0.7])
    words = record_words(rec)
    assert [(w.id, w.text, w.box, w.confidence) for w in words] == [(None, "ab", [0.0, 0.0, 4.0, 4.0], 0.75),
                                                                    (None, "c", [6.0, 0.0, 3.0, 5.0], 0.7)]
    b = max_bbox(rec.cuts[:1])
    assert (b.x0, b.y0, b.x1, b.y1) == (0, 0, 2, 4)
    assert mean_confidence(rec) == pytest.approx(0.8) and mean_confidence(SimpleNamespace()) == 0.0


def test_lines_become_kraken_records():
    t = sample_layout()
    seg = lines_to_segmentation(800, 400, t.lines)
    assert seg.type == "baselines" and [r.id for r in seg.lines] == [ln.id for ln in t.lines]
    boxed = line_record(Line(annotator=0, id="b", box=[10, 10, 2000, 20]), 800, 400)
    assert boxed.type == "bbox" and boxed.bbox == (10, 10, 799, 30)          # clipped to the page
