"""The built-in importers (step import): each passes the engine check on a source document of its format."""
import json

import pytest

from linecaster.data import SourceDocument
from linecaster.engines.importers import IMPORTERS
from linecaster.formats import to_alto, to_hocr, to_page
from linecaster.formats.iiif import to_annotation_page
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
        "import.iiif.v1": lambda: SourceDocument(data=json.dumps(to_annotation_page(
            sample_transcription(), "https://library.test/canvas/1", "https://library.test/anno/1"))),
        "import.tei.v1": lambda: SourceDocument(data='<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><p>One '
                                                     '<hi rend="bold">two</hi></p><p>three</p></body></text></TEI>'),
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


def test_a_source_s_context_states_the_page_s_writing_system():
    from linecaster.engines.importers import AltoImporter, TextImporter

    t = TextImporter()(SourceDocument(data="שלום", context={"language": "he", "script": "Hebr",
                                                             "direction": "horizontal-rl", "title": "x"}))
    assert (t.language("l0"), t.script("l0"), t.direction("l0")) == ("he", "Hebr", "horizontal-rl")
    importer = t.annotators[t.classifications[0].annotator]
    assert (importer.kind, importer.step) == ("rule", "import")
    assert TextImporter()(SourceDocument(data="x", context={"language": "en_US"})).language("") == "en-US"
    with pytest.raises(ValueError, match="direction"):
        TextImporter()(SourceDocument(data="x", context={"direction": "rtl"}))
    # the file's own page language stays
    alto = to_alto(sample_transcription()).replace(b"<Page ", b'<Page LANG="de" ', 1)
    assert AltoImporter()(SourceDocument(data=alto, context={"language": "fr"})).language("") == "de"


def test_a_line_image_s_text_is_one_line_over_the_whole_image():
    from linecaster.engines.importers import TextImporter

    t = TextImporter(line_image=True)(SourceDocument(data="Ἐν ἀρχῇ ἦν ὁ λόγος\n", image_width=900, image_height=64,
                                                     context={"language": "grc"}))
    (ln,) = t.lines
    assert (ln.box, t.text_of(ln), t.language("l0")) == ([0.0, 0.0, 900.0, 64.0], "Ἐν ἀρχῇ ἦν ὁ λόγος", "grc")
    assert [a.settings for a in t.annotators if a.kind == "rule"] == [{"ground_truth": True, "line_image": True}]
    assert TextImporter()(SourceDocument(data="a\nb")).annotators[-1].settings == {"ground_truth": True}
    with pytest.raises(ValueError, match="line break"):
        TextImporter(line_image=True)(SourceDocument(data="one\ntwo"))


def test_iiif_annotation_pages_are_told_apart_and_read():
    from linecaster.engines.importers import AutoImporter
    from linecaster.formats.text import sniff

    data = source("import.iiif.v1").data
    assert sniff(data.encode()) == "iiif" and sniff(b'{"type": "Manifest"}') == "text"
    t = AutoImporter()(SourceDocument(data=data))
    assert t.source.format == "iiif" and "Flora of the Northern Hills" in [t.text_of(ln) for ln in t.lines]


def test_ill_formed_languages_of_an_html_page_are_counted():
    from linecaster.engines.importers import HtmlImporter

    t = HtmlImporter()(SourceDocument(data='<p lang="en US">One</p><p lang="de">zwei</p><p lang="en US">x</p>'))
    rules = next(a for a in t.annotators if a.kind == "rule")
    assert rules.measurements["ill_formed_languages"] == {"en US": 2}
