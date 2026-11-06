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

from ...data.transcription import Line, Source, Transcription
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


def from_text(data: bytes, uri: str | None = None) -> Transcription:
    """Plain text (UTF-8): one line per text line, no geometry."""
    text = data.decode("utf-8-sig")
    return Transcription(lines=[Line(id=f"l{i}", reading_order=i, text=t) for i, t in enumerate(text.splitlines())],
                         source=Source(kind="converted", format="text", uri=uri))


def convert(data: bytes, fmt: str, width: int | None, height: int | None, uri: str | None = None) -> Transcription:
    """``data`` in format ``fmt`` (``auto``: sniffed) as a transcription at an image of ``width`` x ``height``."""
    from ...formats import from_alto, from_hocr, from_page

    fmt = sniff(data) if fmt == "auto" else fmt
    if fmt == "alto":
        return from_alto(data, image_width=width, image_height=height, uri=uri)
    if fmt == "text":
        return from_text(data, uri)
    t = from_page(data, uri=uri) if fmt == "page" else from_hocr(data, uri=uri)
    w, h = t.source.image_width, t.source.image_height
    if width and height and w and h and (w, h) != (width, height):
        t = t.scaled(width / w, height / h)
    return t


class TranscriptionConverter(PageBlock):
    """Read the transcription file that comes with each page into the transcription ``transcription``.

    ``format``: ``auto`` (the media's ``metadata["format"]``, else told from the content), ``alto``, ``page``,
    ``hocr`` or ``text``. ``source``: ``media`` (the page's first document media with bytes) or ``uri`` (the file
    named by ``page.metadata[uri_key]``; ``uri_key`` may be a dotted path into nested metadata). The transcription's
    ``source`` records the format, the file's URI and the page image (hash and size); it replaces whatever the page
    had under that name."""

    name = "📄 transcription converter"
    role = "transform"

    def __init__(self, format: str = "auto", source: str = "media", transcription: str = "ocr_original",
                 uri_key: str | None = None):
        super().__init__()
        if format not in FORMATS:
            raise PipelineConfigError(f"TranscriptionConverter: format is one of {', '.join(FORMATS)}, not {format!r}")
        if source not in SOURCES:
            raise PipelineConfigError(f"TranscriptionConverter: source is media or uri, not {source!r}")
        if (source == "uri") != bool(uri_key):
            raise PipelineConfigError("TranscriptionConverter: source='uri' names the file by uri_key (and only it)")
        self.format, self.source, self.transcription, self.uri_key = format, source, transcription, uri_key

    def contract(self) -> Contract:
        """Reads the delivered file (or the page record that names it) and the image's record; adds whatever the
        file holds (``<transcription>:*``)."""
        reads = {Part("metadata"), Part("transcription_file")} if self.source == "media" else {Part("metadata")}
        return Contract(unit="page", role=self.role, reads=frozenset(reads),
                        adds=frozenset({Part("*", self.transcription)}))

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
        t = convert(data, fmt if fmt in FORMATS else "auto", width, height, uri)
        if image is not None:
            t.source.image_sha256, t.source.image_width, t.source.image_height = image.sha256, width, height
        page.transcriptions[self.transcription] = t
        self.stat_update(f"converted_{t.source.format}")
        return page
