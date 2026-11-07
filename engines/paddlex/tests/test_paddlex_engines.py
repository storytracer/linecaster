"""linecaster-paddlex: the engines' conformance (``linecaster.testing.check_engine``, on the CPU) and their own
helpers. Run in an environment with the package (README: the test command)."""
import numpy as np
import pytest

from linecaster.engines.api import model_entry, weights_of
from linecaster.testing import check_engine
from linecaster_paddlex import (PaddleFormulaEngine, PaddleLayoutEngine, PaddleLineEngine, PaddleRecognitionEngine,
                                PaddleTableEngine)
from linecaster_paddlex.layout import PaddleLayout
from linecaster_paddlex.recognizer import line_rectangle
from linecaster_paddlex.tables import cells_from_html, parse_structure
from linecaster_paddlex.weights import catalog_weights, check, model_id


@pytest.mark.network
@pytest.mark.parametrize("engine, options", [
    (PaddleLayoutEngine, {"model_name": "PP-DocLayoutV3"}),
    (PaddleLineEngine, {"model_name": "PP-OCRv6_tiny_det"}),
    (PaddleRecognitionEngine, {"model_name": "PP-OCRv6_tiny_rec"}),
    (PaddleTableEngine, {}),
], ids=["layout", "lines", "recognition", "tables"])
def test_conformance_on_the_cpu(engine, options):
    out = check_engine(engine, options={**options, "device": "cpu"})
    assert out.steps[-1].revision


@pytest.mark.network
@pytest.mark.slow
def test_formula_conformance_on_the_cpu():
    out = check_engine(PaddleFormulaEngine, options={"model_name": "PP-FormulaNet-L", "device": "cpu"})
    assert isinstance(next(r for r in out.regions if r.label == "formula").extra.get("formula"), str)


def test_models_resolve_through_the_catalog():
    assert model_id("PP-OCRv6_medium_det") == "pp-ocrv6-medium-det-onnx"
    assert model_entry("pp-ocrv6-medium-det-onnx") is not None and model_entry("pp-ocrv5-server-det-onnx") is None
    assert catalog_weights("PP-OCRv5_server_det") is None          # not pinned: PaddleX downloads it itself
    assert catalog_weights("PP-OCRv6_tiny_det") == weights_of("pp-ocrv6-tiny-det-onnx")
    with pytest.raises(ValueError, match="does not name the pinned weights"):
        check("PP-OCRv6_tiny_det", weights_of("pp-ocrv6-medium-det-onnx"))


def test_a_line_rectangle_starts_top_left():
    rect = line_rectangle([[110, 40], [10, 40], [10, 10], [110, 10]])
    assert np.allclose(rect[0], [10, 10]) and np.allclose(rect[2], [110, 40])


def test_table_structure_tokens_and_html():
    assert parse_structure(["<tr>", "<td></td>", "<td", ' colspan="2"', ">", "</td>", "</tr>"]) == [
        (0, 0, 1, 1), (0, 1, 1, 2)]
    cells = cells_from_html("<table><tr><td>a</td><td>b</td></tr><tr><td colspan='2'>c</td></tr></table>")
    assert [(c.text, c.row, c.col) for c in cells] == [("a", 0, 0), ("b", 0, 1), ("c", 1, 0)]


class _Boxes:
    """A predictor that returns fixed layout boxes without ``order`` (as PP-DocLayout_plus-L does)."""

    def __init__(self, boxes):
        self.boxes = boxes

    def predict(self, image, **kwargs):
        yield {"boxes": self.boxes}


@pytest.mark.parametrize("reading_order, expected", [
    ("xy-cut", ["text_0", "text_1", "text_2", "text_3"]),        # the aligned gaps cut across both columns
    ("xy-cut++", ["text_0", "text_2", "text_1", "text_3"]),
])
def test_regions_without_learned_order_follow_reading_order(reading_order, expected):
    boxes = [{"coordinate": c, "label": "text", "score": 0.9} for c in
             ([100, 100, 480, 500], [520, 100, 900, 500], [100, 520, 480, 1300], [520, 520, 900, 1300])]
    layout = PaddleLayout.__new__(PaddleLayout)
    layout.predictor, layout.threshold, layout.nms, layout.merge_mode = _Boxes(boxes), 0.5, True, "large"
    layout.header_zone, layout.max_containment, layout.reading_order = 0.15, 0.8, reading_order
    regions = layout.analyze(np.zeros((1400, 1000, 3), dtype=np.uint8))
    assert [r.id for r in sorted(regions, key=lambda r: r.order)] == expected
