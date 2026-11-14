"""The built-in importers (step import): each passes the engine check on a source document of its format."""
import json

import pytest

from linecaster.data import SourceDocument
from linecaster.engines.importers import IMPORTERS
from linecaster.formats import to_alto, to_hocr, to_page
from linecaster.testing import check_engine, sample_transcription


def source(engine_id: str) -> SourceDocument:
    from linecaster.testing.conformance import docling_sample

    if engine_id == "import.docling.v1":
        pytest.importorskip("docling_core")
    t = sample_transcription()
    return {
        "import.alto.v1": lambda: SourceDocument(data=to_alto(t), format="alto"),
        "import.page.v1": lambda: SourceDocument(data=to_page(t), format="page"),
        "import.hocr.v1": lambda: SourceDocument(data=to_hocr(t), format="hocr"),
        "import.auto.v1": lambda: SourceDocument(data=to_page(t)),
        "import.text.v1": lambda: SourceDocument(data="one\ntwo"),
        "import.docling.v1": lambda: SourceDocument(data=json.dumps(docling_sample(t))),
        "import.html.v1": lambda: SourceDocument(data="<p>One <b>two</b></p><p>three</p>"),
    }[engine_id]()


@pytest.mark.parametrize("engine_id", sorted(IMPORTERS))
def test_every_importer_passes_the_engine_check(engine_id):
    out = check_engine(IMPORTERS[engine_id], source=source(engine_id))
    assert out.source.kind == "ground_truth" and out.lines


def test_a_delivered_file_and_the_page_image():
    t = sample_transcription()
    out = IMPORTERS["import.alto.v1"](ground_truth=False)(
        SourceDocument(data=to_alto(t.scaled(0.5), image_width=400, image_height=200), image_width=800,
                       image_height=400, uri="https://library.test/ocr/1.xml", record="1", revision="r2"))
    assert (out.source.kind, out.source.uri, out.source.record, out.source.revision) == (
        "converted", "https://library.test/ocr/1.xml", "1", "r2")
    assert (out.source.image_width, out.source.image_height) == (800, 400)
    assert out.lines[0].box == pytest.approx(t.lines[0].box, abs=2.0)
