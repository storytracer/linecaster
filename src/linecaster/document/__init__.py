"""linecaster's document: a page or an item as a reader reads it (``model``), built from transcriptions
(``builder``) and written out as HTML, Markdown, text and JSON (``serialize``)."""
from linecaster.document.builder import KIND_OF_ROLE, DocumentBuilder, block_kind, build_document
from linecaster.document.model import KINDS, SCHEMA, Block, Document, Grid, Origin, Page, Span
from linecaster.document.serialize import EXPORT_FORMATS, export, from_json, load_document, table_html, to_html, to_json, to_markdown, \
    to_text

#: the ``Document.metadata`` keys of a composed page or item (``DocumentComposer``): the document (as a dict) and, for a page,
#: the transcription it was composed from
DOCUMENT_KEY, COMPOSED_KEY = "document", "document_transcription"

__all__ = ["COMPOSED_KEY", "DOCUMENT_KEY", "Block", "Document", "DocumentBuilder", "EXPORT_FORMATS", "Grid", "KINDS", "KIND_OF_ROLE", "Origin", "Page",
           "SCHEMA", "Span", "block_kind", "build_document", "export", "from_json", "load_document", "table_html",
           "to_html", "to_json", "to_markdown", "to_text"]
