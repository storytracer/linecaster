"""``TranscriptionImporter``: a page's source document read into a named transcription of the page record by an
importer (an engine of step ``import``): a library's own OCR (ALTO, PAGE-XML, hOCR, text) into ``ocr_original``, a
ground truth into ``ground_truth``, a source's markup through an engine package's importer.

The document comes with the page as a document media (``source="media"``: what ``ManifestReader(existing_ocr=True)``
brings, its format in the media's ``metadata["format"]``), is named by a URI in the page's metadata
(``source="uri"``, ``uri_key``: any fsspec path or URL), or stands in the page's metadata itself
(``source="metadata"``, ``data_key``: a table's column, such as a wiki page's wikitext). A document that cannot be read
is the page's error; a page without one passes unchanged.
"""
from __future__ import annotations

from typing import Any

from datatrove.data import MediaType

from linecaster.data.source import SourceDocument
from linecaster.errors import PipelineConfigError
from linecaster.core.contract import Contract, Part
from linecaster.core.page import PageComponent
from linecaster.core.rule import now, rule_backend, stamp

#: where the document comes from
SOURCES = ("media", "uri", "metadata")


def _dotted(d, key: str):
    for k in key.split("."):
        d = d.get(k) if isinstance(d, dict) else None
    return d


class TranscriptionImporter(PageComponent):
    """Reads each page's source document into a named transcription, by an importer.

    The importer (a preset of step ``import``, e.g. ``auto-import``, or an engine spec ``InProcess(...)``) reads the
    document at the page image's size (a file that states another size is scaled to it). The transcription replaces
    whatever the page had under that name; its ``source`` records the format, the document's URI or record and the
    page image (hash and size). With ``context_keys``, values of the page's metadata go to the importer as the
    document's context (a wiki page's title); ``record``, ``revision`` and ``dataset`` go to the source's fields.

    Args:
        importer: the importer: a preset (``id``) of step ``import`` or an ``InProcess`` engine spec.
        source: ``media`` (the page's first document media with bytes), ``uri`` (the file named by ``uri_key``) or
            ``metadata`` (the content in the page's metadata under ``data_key``).
        transcription: the name of the transcription it fills.
        uri_key: with ``source="uri"``: the key of ``page.metadata`` that holds the file's URI (dotted for nested
            metadata).
        data_key: with ``source="metadata"``: the key of ``page.metadata`` that holds the document's content.
        context_keys: keys of ``page.metadata`` given to the importer as the document's context.
        options: importer options over the preset's (``ground_truth``, ``conventions``, an engine's own).

    Example:
        TranscriptionImporter("auto-import", transcription="ocr_original", options={"ground_truth": False})
    """

    name = "📄 transcription importer"
    kind = "transform"
    step = "import"
    docs_args = {"importer": "auto-import"}

    def __init__(self, importer="auto-import", source: str = "media", transcription: str = "ground_truth",
                 uri_key: str | None = None, data_key: str | None = None, context_keys: tuple[str, ...] = (),
                 options: dict[str, Any] | None = None):
        super().__init__()
        if source not in SOURCES:
            raise PipelineConfigError(f"TranscriptionImporter: source is one of {', '.join(SOURCES)}, not {source!r}")
        if (source == "uri") != bool(uri_key):
            raise PipelineConfigError("TranscriptionImporter: source='uri' names the file by uri_key (and only it)")
        if (source == "metadata") != bool(data_key):
            raise PipelineConfigError("TranscriptionImporter: source='metadata' names the content by data_key (and "
                                      "only it)")
        self.backend = rule_backend(importer, self.step, options)
        self.source, self.transcription, self.uri_key, self.data_key = source, transcription, uri_key, data_key
        self.context_keys = tuple(context_keys)

    def init_params(self) -> dict[str, Any]:
        """The parameters, ``importer`` as the backend it resolved to (engine, options, preset and hash)."""
        out = super().init_params()
        out["importer"] = self.backend
        return out

    def contract(self) -> Contract:
        """Reads the document (or the page record that names or holds it) and the image's record; adds whatever
        the importer reads and replaces what the page had under that name (``<transcription>:*``)."""
        reads = {Part("metadata"), Part("transcription_file")} if self.source == "media" else {Part("metadata")}
        made = frozenset({Part("*", self.transcription)})
        return Contract(unit="page", kind=self.kind, reads=frozenset(reads), adds=made, replaces=made)

    def warm_up(self) -> None:
        self.backend.warm_up()

    def _document(self, doc, page) -> tuple[bytes | str, str | None, str | None] | None:
        """The document's content, its URI and its format hint, or None when the page has none."""
        if self.source == "media":
            m = next((m for m in doc.media if m.type == MediaType.DOCUMENT and m.media_bytes is not None), None)
            if m is None:
                return None
            return m.media_bytes, m.url or None, (m.metadata or {}).get("format")
        if self.source == "metadata":
            data = _dotted(page.metadata, self.data_key)
            return (data, None, None) if data else None
        uri = _dotted(page.metadata, self.uri_key)
        if not uri:
            return None
        from linecaster.components.images.image_converter import read_uri

        return read_uri(str(uri)), str(uri), None

    def process_page(self, doc, page):
        found = self._document(doc, page)
        if found is None:
            self.stat_update("pages_without_document")
            return page
        data, uri, fmt = found
        image = page.image
        context = {k: _dotted(page.metadata, k) for k in self.context_keys}
        revision = context.pop("revision", None)
        source = SourceDocument(data=data, format=fmt, uri=uri, record=context.pop("record", None),
                                revision=str(revision) if revision is not None else None,
                                dataset=context.pop("dataset", None), image_width=image.width if image else None,
                                image_height=image.height if image else None, context=context)
        start, began = now()
        t = self.backend.model()(source)
        for info in t.annotators:
            if info.kind == "rule" and info.step == "import":
                stamp(info, self.backend, start, began)
        if image is not None:
            t.source.image_sha256 = image.sha256
        page.transcriptions[self.transcription] = t
        self.stat_update(f"imported_{t.source.format}")
        return page
