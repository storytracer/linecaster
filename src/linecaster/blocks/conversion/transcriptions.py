"""``TranscriptionConverter``: a library's own transcription of a page (ALTO, PAGE-XML, hOCR or plain text) read into
a named transcription of the page record (default ``ocr_original``).

The file comes with the page as a document media (``source="media"``: what ``ManifestReader(existing_ocr=True)``
brings, its format in the media's ``metadata["format"]``) or is named by a URI in the page's metadata
(``source="uri"``, ``uri_key``: any fsspec path or URL). It is read with linecaster's ``from_alto`` / ``from_page`` /
``from_hocr`` (or as lines of plain text) at the page image's size: ALTO is scaled to the image by its own page size,
PAGE-XML and hOCR by the image size they state, when it differs. A file that cannot be read is the page's error; a
page without one passes unchanged.
"""
from __future__ import annotations

import re

from datatrove.data import MediaType

from ...data.transcription import Annotator, Source, Transcription
from ...errors import PipelineConfigError
from ..base.contract import Contract, Part
from ..base.page import PageBlock

#: the formats it reads; ``auto`` tells them apart (the media's format, else the content)
FORMATS = ("auto", "alto", "page", "hocr", "text")
#: where the file comes from
SOURCES = ("media", "uri")
_ROOT = re.compile(rb"<(?:[\w.-]+:)?(alto|pcgts)\b", re.IGNORECASE)
_HOCR = re.compile(rb"""class\s*=\s*["'][^"']*\bocr_page\b""", re.IGNORECASE)


def sniff(data: bytes) -> str:
    """The format of a transcription file from its content: ``alto``, ``page``, ``hocr``, else ``text``."""
    m = _ROOT.search(data[:65536])
    if m:
        return "alto" if m.group(1).lower() == b"alto" else "page"
    if _HOCR.search(data):
        return "hocr"
    return "text"


def from_text(data: bytes, uri: str | None = None, ground_truth: bool = False) -> Transcription:
    """Plain text (UTF-8): one line per text line, no geometry, read by the file (one annotator, kind ``file``;
    ``ground_truth``: by people, kind ``human``, the source a ground truth), in the file's order."""
    text = data.decode("utf-8-sig")
    t = Transcription(source=Source(kind="ground_truth" if ground_truth else "converted", format="text", uri=uri))
    a = t.add_annotator(Annotator(kind="human" if ground_truth else "file", step="transcription", name="text"))
    for i, line in enumerate(text.splitlines()):
        t.add_line(a, f"l{i}", text=line)
    t.add_order(a, lines=[ln.id for ln in t.lines])
    return t


def convert(data: bytes, fmt: str, width: int | None, height: int | None, uri: str | None = None,
            ground_truth: bool = False) -> Transcription:
    """``data`` in format ``fmt`` (``auto``: sniffed) as a transcription at an image of ``width`` x ``height``;
    ``ground_truth``: the file is a ground truth (the readers' ``ground_truth``)."""
    from ...formats import from_alto, from_hocr, from_page

    fmt = sniff(data) if fmt == "auto" else fmt
    if fmt == "alto":
        return from_alto(data, image_width=width, image_height=height, uri=uri, ground_truth=ground_truth)
    if fmt == "text":
        return from_text(data, uri, ground_truth)
    read = from_page if fmt == "page" else from_hocr
    t = read(data, uri=uri, ground_truth=ground_truth)
    w, h = t.source.image_width, t.source.image_height
    if width and height and w and h and (w, h) != (width, height):
        t = t.scaled(width / w, height / h)
    return t


class TranscriptionConverter(PageBlock):
    """Reads the transcription file that comes with each page (ALTO, PAGE-XML, hOCR or plain text) into a named
    transcription.

    The file is a document media of the page (``source="media"``: what ``ManifestReader(existing_ocr=True)`` brings,
    the part ``transcription_file``) or is named by a URI in the page's metadata (``source="uri"``). It is read with
    linecaster's ``from_alto`` / ``from_page`` / ``from_hocr`` (or as lines of plain text) at the page image's size:
    ALTO is scaled to the image by its own page size, PAGE-XML and hOCR by the image size they state, when it
    differs. It adds whatever the file holds (``<transcription>:*``) and replaces whatever the page had under that
    name; the transcription's ``source`` records the format, the file's URI and the page image (hash and size), and
    its annotators are the steps the file names, else the file itself (kind ``file``; with ``ground_truth``,
    people: kind ``human``, and ``source.kind`` ``ground_truth``). A file that cannot be read is the page's error; a page without one passes unchanged (``pages_without_file``). The
    builder puts one after a reader that brings transcription files when the pipeline has none.

    Args:
        format: ``auto`` (the media's ``metadata["format"]``, else told from the content), ``alto``, ``page``,
            ``hocr`` or ``text``.
        source: ``media`` (the page's first document media with bytes) or ``uri`` (the file named by
            ``uri_key``).
        transcription: the name of the transcription it fills.
        uri_key: the key of ``page.metadata`` that holds the file's URI (any fsspec path or URL), a dotted path into
            nested metadata; needed with ``source="uri"`` and only then.
        ground_truth: the files are ground truths, made or checked by people (plain text: lines without geometry).
    """

    name = "📄 transcription converter"
    role = "transform"

    def __init__(self, format: str = "auto", source: str = "media", transcription: str = "ocr_original",
                 uri_key: str | None = None, ground_truth: bool = False):
        super().__init__()
        if format not in FORMATS:
            raise PipelineConfigError(f"TranscriptionConverter: format is one of {', '.join(FORMATS)}, not {format!r}")
        if source not in SOURCES:
            raise PipelineConfigError(f"TranscriptionConverter: source is media or uri, not {source!r}")
        if (source == "uri") != bool(uri_key):
            raise PipelineConfigError("TranscriptionConverter: source='uri' names the file by uri_key (and only it)")
        self.format, self.source, self.transcription, self.uri_key = format, source, transcription, uri_key
        self.ground_truth = ground_truth

    def contract(self) -> Contract:
        """Reads the delivered file (or the page record that names it) and the image's record; adds whatever the
        file holds and replaces what the page had under that name (``<transcription>:*``)."""
        reads = {Part("metadata"), Part("transcription_file")} if self.source == "media" else {Part("metadata")}
        made = frozenset({Part("*", self.transcription)})
        return Contract(unit="page", role=self.role, reads=frozenset(reads), adds=made, replaces=made)

    def _file(self, doc, page) -> tuple[bytes, str | None, str] | None:
        """The file's bytes, its URI and its format hint, or None when the page has none."""
        if self.source == "media":
            m = next((m for m in doc.media if m.type == MediaType.DOCUMENT and m.media_bytes is not None), None)
            if m is None:
                return None
            return m.media_bytes, m.url or None, (m.metadata or {}).get("format") or self.format
        uri = page.metadata
        for key in self.uri_key.split("."):
            uri = uri.get(key) if isinstance(uri, dict) else None
        if not uri:
            return None
        from .images import read_uri

        return read_uri(str(uri)), str(uri), self.format

    def process_page(self, doc, page):
        found = self._file(doc, page)
        if found is None:
            self.stat_update("pages_without_file")
            return page
        data, uri, fmt = found
        fmt = fmt if self.format == "auto" else self.format
        image = page.image
        width, height = (image.width, image.height) if image else (None, None)
        t = convert(data, fmt if fmt in FORMATS else "auto", width, height, uri, self.ground_truth)
        if image is not None:
            t.source.image_sha256, t.source.image_width, t.source.image_height = image.sha256, width, height
        page.transcriptions[self.transcription] = t
        self.stat_update(f"converted_{t.source.format}")
        return page
