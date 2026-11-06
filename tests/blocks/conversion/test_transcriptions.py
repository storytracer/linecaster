"""TranscriptionConverter: a library's own transcription (ALTO, PAGE-XML, hOCR, plain text) delivered with the
page, read into ocr_original at the page image's size; and the builder putting one after a reader that brings it."""
from __future__ import annotations

import io

import pytest
from datatrove.data import Media, MediaType
from PIL import Image

from conftest import make_transcription
from linecaster.blocks.base.page import new_page_document, page_of, set_page
from linecaster.blocks.conversion import TranscriptionConverter
from linecaster.blocks.conversion.transcriptions import sniff
from linecaster.errors import PipelineConfigError
from linecaster.formats import to_alto, to_hocr, to_page

W, H = 1600, 2200


def page(file: bytes | None = None, fmt: str | None = None, metadata: dict | None = None):
    buf = io.BytesIO()
    Image.new("RGB", (W, H), "white").save(buf, format="PNG")
    doc = new_page_document("p1", buf.getvalue(), item_id="b1", sequence=1, metadata=metadata)
    if file is not None:
        doc.media.append(Media(id="p1.ocr", type=MediaType.DOCUMENT, url="https://lib.example/ocr/p1",
                               media_bytes=file, metadata={"format": fmt} if fmt else {}))
    return doc


def run(block, *docs):
    return list(block.run(iter(docs)))


@pytest.mark.parametrize("fmt, write", [("alto", to_alto), ("page", to_page), ("hocr", to_hocr)])
def test_the_formats_at_the_page_images_size(fmt, write):
    """A file made on an image half the size is read at the page image's size; the format comes from the media's
    hint or, without one, from the content."""
    original = make_transcription()
    half = write(original.scaled(0.5), image_width=W // 2, image_height=H // 2)
    for hint in (fmt, None):
        [doc] = run(TranscriptionConverter(), page(half, hint))
        t = page_of(doc).transcriptions["ocr_original"]
        assert (t.source.kind, t.source.format, t.source.uri) == ("converted", fmt, "https://lib.example/ocr/p1")
        assert (t.source.image_width, t.source.image_height) == (W, H)
        assert t.source.image_sha256 == page_of(doc).image.sha256
        assert t.text == original.text
        assert t.lines[1].bbox == pytest.approx(original.lines[1].bbox, abs=2.0)
        assert "ocr_new" not in page_of(doc).transcriptions and "errors" not in doc.metadata
    assert sniff(half) == fmt


def test_plain_text_a_uri_and_pages_without_a_file(tmp_path):
    [doc] = run(TranscriptionConverter(format="text", transcription="ground_truth"), page("ein\nzwei\n".encode()))
    t = page_of(doc).transcriptions["ground_truth"]
    assert [ln.text for ln in t.lines] == ["ein", "zwei"] and t.lines[0].bbox is None and t.source.format == "text"
    (tmp_path / "p1.xml").write_bytes(to_alto(make_transcription(), image_width=W, image_height=H))
    by_uri = TranscriptionConverter(source="uri", uri_key="library.ocr")
    [doc] = run(by_uri, page(metadata={"library": {"ocr": str(tmp_path / "p1.xml")}}))
    assert page_of(doc).transcriptions["ocr_original"].source.uri == str(tmp_path / "p1.xml")
    block = TranscriptionConverter()
    [doc] = run(block, page())                                  # nothing delivered: the page passes unchanged
    assert "ocr_original" not in page_of(doc).transcriptions and block.stats["pages_without_file"].total == 1
    with pytest.raises(PipelineConfigError):
        TranscriptionConverter(source="uri")
    with pytest.raises(PipelineConfigError):
        TranscriptionConverter(format="pdf")


def test_a_file_that_cannot_be_read_is_the_pages_error():
    [doc] = run(TranscriptionConverter(format="alto"), page(b"<alto><Layout><Page"))
    [entry] = doc.metadata["errors"]
    assert entry["block"] == "TranscriptionConverter" and "ocr_original" not in page_of(doc).transcriptions


def test_the_builder_puts_a_converter_after_a_reader_that_brings_the_file(tmp_path):
    pytest.importorskip("pybookget")
    from linecaster.blocks.readers import ManifestReader
    from linecaster.blocks.writers import PageJsonlWriter
    from linecaster.runtime.builder import build

    def blocks(p):
        return [type(b).__name__ for b in p.blocks]

    reader = ManifestReader(str(tmp_path), existing_ocr=True)
    p = build([reader, PageJsonlWriter(str(tmp_path / "out"))])
    assert blocks(p) == ["ManifestReader", "TranscriptionConverter", "PageJsonlWriter"] and not p.problems
    own = TranscriptionConverter(transcription="library")
    p = build([ManifestReader(str(tmp_path), existing_ocr=True), own, PageJsonlWriter(str(tmp_path / "out"))])
    assert blocks(p) == ["ManifestReader", "TranscriptionConverter", "PageJsonlWriter"] and p.blocks[1] is own
    assert "TranscriptionConverter" not in blocks(build([ManifestReader(str(tmp_path)), PageJsonlWriter("o")]))
