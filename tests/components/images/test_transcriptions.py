"""TranscriptionImporter: a page's source document read by an importer (step import): a library's own transcription
(ALTO, PAGE-XML, hOCR, plain text) delivered with the page into ocr_original at the page image's size, a ground
truth, a document in the page's metadata; and the builder putting one after a reader that brings a file."""
from __future__ import annotations

import io

import pytest
from datatrove.data import Media, MediaType
from PIL import Image

from conftest import sample_transcription
from linecaster.backends import InProcess
from linecaster.core.page import new_page_document, page_of
from linecaster.components.importers import TranscriptionImporter
from linecaster.errors import PipelineConfigError
from linecaster.formats import to_alto, to_hocr, to_page
from linecaster.formats.text import sniff

W, H = 1600, 2200
LIBRARY = {"transcription": "ocr_original", "options": {"ground_truth": False}}


def page(file: bytes | None = None, fmt: str | None = None, metadata: dict | None = None):
    buf = io.BytesIO()
    Image.new("RGB", (W, H), "white").save(buf, format="PNG")
    doc = new_page_document("p1", buf.getvalue(), item_id="b1", sequence=1, metadata=metadata)
    if file is not None:
        doc.media.append(Media(id="p1.ocr", type=MediaType.DOCUMENT, url="https://lib.example/ocr/p1",
                               media_bytes=file, metadata={"format": fmt} if fmt else {}))
    return doc


def run(component, *docs):
    return list(component.run(iter(docs)))


@pytest.mark.parametrize("fmt, write", [("alto", to_alto), ("page", to_page), ("hocr", to_hocr)])
def test_the_formats_at_the_page_images_size(fmt, write):
    """A file made on an image half the size is read at the page image's size; the format comes from the media's
    hint or, without one, from the content."""
    original = sample_transcription()
    half = write(original.scaled(0.5), image_width=W // 2, image_height=H // 2)
    for hint in (fmt, None):
        [doc] = run(TranscriptionImporter("auto-import", **LIBRARY), page(half, hint))
        t = page_of(doc).transcriptions["ocr_original"]
        assert (t.source.kind, t.source.format, t.source.uri) == ("converted", fmt, "https://lib.example/ocr/p1")
        assert (t.source.image_width, t.source.image_height) == (W, H)
        assert t.source.image_sha256 == page_of(doc).image.sha256
        assert t.text == original.text
        assert t.lines[1].box == pytest.approx(original.lines[1].box, abs=2.0)
        assert all(a.kind != "human" for a in t.annotators)
        assert "ocr_new" not in page_of(doc).transcriptions and "errors" not in doc.metadata
    assert sniff(half) == fmt


def test_plain_text_a_uri_metadata_and_pages_without_a_document(tmp_path):
    [doc] = run(TranscriptionImporter("text-import", options={"ground_truth": False}), page("ein\nzwei\n".encode()))
    t = page_of(doc).transcriptions["ground_truth"]
    assert [ln.reading.text for ln in t.lines] == ["ein", "zwei"] and t.lines[0].box is None
    assert (t.source.kind, t.source.format, [a.kind for a in t.annotators]) == ("converted", "text", ["file", "rule"])
    assert (t.annotators[1].engine, t.annotators[1].preset) == ("import.text.v1", "text-import")
    (tmp_path / "p1.xml").write_bytes(to_alto(sample_transcription(), image_width=W, image_height=H))
    by_uri = TranscriptionImporter("auto-import", source="uri", uri_key="library.ocr", **LIBRARY)
    [doc] = run(by_uri, page(metadata={"library": {"ocr": str(tmp_path / "p1.xml")}}))
    assert page_of(doc).transcriptions["ocr_original"].source.uri == str(tmp_path / "p1.xml")
    in_metadata = TranscriptionImporter("text-import", source="metadata", data_key="row.text",
                                        context_keys=("row.id",))
    [doc] = run(in_metadata, page(metadata={"row": {"text": "eins\nzwei", "id": "r1"}}))
    assert page_of(doc).transcriptions["ground_truth"].source.kind == "ground_truth"
    component = TranscriptionImporter("auto-import", **LIBRARY)
    [doc] = run(component, page())                                  # nothing delivered: the page passes unchanged
    assert "ocr_original" not in page_of(doc).transcriptions and component.stats["pages_without_document"].total == 1
    with pytest.raises(PipelineConfigError):
        TranscriptionImporter("auto-import", source="uri")
    with pytest.raises(PipelineConfigError):
        TranscriptionImporter("auto-import", source="metadata")
    with pytest.raises(PipelineConfigError):
        TranscriptionImporter("ratios")                       # a preset of another step


@pytest.mark.parametrize("preset, write", [("alto-import", to_alto), ("page-xml-import", to_page),
                                           ("hocr-import", to_hocr), ("text-import", None)])
def test_a_ground_truth(preset, write):
    """A ground truth by default: the source is one and, where the file names no steps, people read it; plain text
    gives lines without geometry."""
    data = write(sample_transcription(), image_width=W, image_height=H) if write else "ein\nzwei".encode()
    [doc] = run(TranscriptionImporter(preset), page(data))
    t = page_of(doc).transcriptions["ground_truth"]
    assert t.source.kind == "ground_truth" and "errors" not in doc.metadata
    if write is None:
        assert [(ln.reading.text, ln.box, ln.polygon) for ln in t.lines] == [("ein", None, None), ("zwei", None, None)]
        assert [(a.kind, a.step) for a in t.annotators] == [("human", "transcription"), ("rule", "import")]


def test_an_engine_spec_and_html():
    html = b"<html><body><p>One <i>two</i></p><p class='edit'>[edit]</p></body></html>"
    [doc] = run(TranscriptionImporter(InProcess("linecaster.engines.importers:HtmlImporter")), page(html))
    t = page_of(doc).transcriptions["ground_truth"]
    assert [ln.reading.text for ln in t.lines] == ["One two", "[edit]"]
    assert t.annotators[1].engine == "import.html.v1" and "seconds" in t.annotators[1].measurements


def test_a_file_that_cannot_be_read_is_the_pages_error():
    [doc] = run(TranscriptionImporter("alto-import", **LIBRARY), page(b"<alto><Layout><Page"))
    [entry] = doc.metadata["errors"]
    assert entry["component"] == "TranscriptionImporter" and "ocr_original" not in page_of(doc).transcriptions


def test_the_builder_puts_an_importer_after_a_reader_that_brings_the_file(tmp_path):
    from linecaster.components.readers import ManifestReader
    from linecaster.components.writers import PageJsonlWriter
    from linecaster.runtime.builder import build

    def components(p):
        return [type(b).__name__ for b in p.components]

    reader = ManifestReader(str(tmp_path), existing_ocr=True)
    p = build([reader, PageJsonlWriter(str(tmp_path / "out"))])
    assert components(p) == ["ManifestReader", "TranscriptionImporter", "PageJsonlWriter"] and not p.problems
    assert p.components[1].transcription == "ocr_original"
    own = TranscriptionImporter("auto-import", transcription="library")
    p = build([ManifestReader(str(tmp_path), existing_ocr=True), own, PageJsonlWriter(str(tmp_path / "out"))])
    assert components(p) == ["ManifestReader", "TranscriptionImporter", "PageJsonlWriter"] and p.components[1] is own
    assert "TranscriptionImporter" not in components(build([ManifestReader(str(tmp_path)), PageJsonlWriter("o")]))
