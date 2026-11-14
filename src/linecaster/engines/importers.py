"""The import step: engines that read a source document (``linecaster.data.SourceDocument``) into a transcription,
in the pipeline's process.

An importer (``Importer``) is a rule-based engine of step ``import``: ``__call__(source, **options)`` for its unit
``page`` (an item-unit importer takes the item's documents and returns a transcription per page). The base does
what every importer shares: the options (``ground_truth``: the source is a ground truth, read by people), the
source's fields on the transcription (record, revision, dataset, URI), and the fit to the page image (a
transcription whose coordinates refer to an image of another size is scaled to the page's). The formats themselves
are ``linecaster.formats``; the importers are thin.

Built in: ``import.alto.v1``, ``import.page.v1``, ``import.hocr.v1``, ``import.text.v1``, ``import.docling.v1``,
``import.html.v1`` (with a source's ``conventions``) and ``import.auto.v1`` (tells ALTO, PAGE-XML, hOCR and text
apart and reads each with its importer). Engine packages add importers for formats that need more (a wiki's
wikitext: ``linecaster-mediawiki``).
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from ..data.source import SourceDocument
from ..data.transcription import Annotator, Transcription
from .base import RuleEngine

class Importer(RuleEngine):
    """Base of the importers. A subclass states ``engine_id``, ``format`` and ``Options``, and implements
    ``read(source, options)``."""

    step: ClassVar[str] = "import"
    format: ClassVar[str]
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["regions", "reading_order", "lines", "text"]}

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")
        ground_truth: bool = Field(True, description="the source is a ground truth, made or checked by people (else "
                                                     "a delivered file whose making is unknown)")

    def read(self, source: SourceDocument, options) -> Transcription:  # pragma: no cover - interface
        raise NotImplementedError

    def __call__(self, source: SourceDocument, **options) -> Transcription:
        o = self.configured(options)
        t = self.read(source, o)
        s = t.source
        s.kind = "ground_truth" if o.ground_truth else "converted"
        s.format = s.format or self.format
        s.uri, s.record = s.uri or source.uri, s.record or source.record
        s.revision, s.dataset = s.revision or source.revision, s.dataset or source.dataset
        w, h = s.image_width, s.image_height
        if source.image_width and source.image_height and w and h and (w, h) != (source.image_width,
                                                                              source.image_height):
            t = t.scaled(source.image_width / w, source.image_height / h)
        if source.image_width and source.image_height:
            t.source.image_width, t.source.image_height = source.image_width, source.image_height
        return t


class AltoImporter(Importer):
    """ALTO (v1 to v4), scaled to the page image by the file's own page size.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "import.alto.v1"
    step: ClassVar[str] = "import"
    format: ClassVar[str] = "alto"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["regions", "reading_order", "lines", "text"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    def read(self, source, options):
        from ..formats import from_alto

        return from_alto(source.as_bytes(), image_width=source.image_width, image_height=source.image_height,
                         uri=source.uri, ground_truth=options.ground_truth)


class PageXmlImporter(Importer):
    """PAGE-XML, scaled to the page image by the image size it states.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "import.page.v1"
    step: ClassVar[str] = "import"
    format: ClassVar[str] = "page"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["regions", "reading_order", "lines", "text"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    def read(self, source, options):
        from ..formats import from_page

        return from_page(source.as_bytes(), uri=source.uri, ground_truth=options.ground_truth)


class HocrImporter(Importer):
    """hOCR, scaled to the page image by the image size it states.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "import.hocr.v1"
    step: ClassVar[str] = "import"
    format: ClassVar[str] = "hocr"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["regions", "reading_order", "lines", "text"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    def read(self, source, options):
        from ..formats import from_hocr

        return from_hocr(source.as_bytes(), uri=source.uri, ground_truth=options.ground_truth)


class TextImporter(Importer):
    """Plain text: a line per line, no geometry.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "import.text.v1"
    step: ClassVar[str] = "import"
    format: ClassVar[str] = "text"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["reading_order", "lines", "text"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    def read(self, source, options):
        from ..formats.text import from_text

        return from_text(source.data, uri=source.uri, ground_truth=options.ground_truth)


class DoclingImporter(Importer):
    """A DoclingDocument (JSON): a region per item, on the page ``page_no`` or every page.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "import.docling.v1"
    step: ClassVar[str] = "import"
    format: ClassVar[str] = "docling"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["regions", "reading_order", "lines", "text"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(Importer.Options):
        page_no: int | None = Field(None, description="the document's page to read (None: every page)")

    def read(self, source, options):
        from ..formats.docling import from_docling

        return from_docling(source.as_text(), page_no=options.page_no, ground_truth=options.ground_truth,
                            dataset=source.dataset, record=source.record)


class HtmlImporter(Importer):
    """HTML, by HTML's semantics and a source's conventions (``conventions``: a catalog entry, ``id@edition``).

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "import.html.v1"
    step: ClassVar[str] = "import"
    format: ClassVar[str] = "html"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["regions", "reading_order", "lines", "text"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(Importer.Options):
        conventions: str | None = Field(None, description="the source's conventions, a catalog entry (id@edition)")

    def read(self, source, options):
        from lxml import html as lxml_html

        from ..formats.html import HtmlConverter
        from .api import conventions as resolve_conventions

        c = resolve_conventions(options.conventions) if options.conventions else None
        t = Transcription()
        people = t.add_annotator(Annotator(kind="human" if options.ground_truth else "file", step="transcription",
                                           name="html"))
        rules = t.add_annotator(self.annotator(options))
        if c is not None:
            t.annotators[rules].conventions, t.annotators[rules].conventions_sha256 = c.ref, c.sha256
        reading = HtmlConverter(c).read(lxml_html.fromstring(source.as_bytes()), t, people, rules)
        t.annotators[rules].measurements.update({**reading.coverage.measurements(),
                                                 "ends_paragraph": reading.ends_paragraph})
        return t


class AutoImporter(Importer):
    """ALTO, PAGE-XML, hOCR or text, told apart by the document's format, else by its content.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "import.auto.v1"
    step: ClassVar[str] = "import"
    format: ClassVar[str] = "auto"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["regions", "reading_order", "lines", "text"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)
    BY_FORMAT: ClassVar[dict[str, type[Importer]]] = {"alto": AltoImporter, "page": PageXmlImporter,
                                                       "hocr": HocrImporter, "text": TextImporter}

    def read(self, source, options):
        from ..formats.text import sniff

        fmt = source.format if source.format in self.BY_FORMAT else sniff(source.as_bytes())
        return self.BY_FORMAT[fmt](ground_truth=options.ground_truth).read(source, options)


#: the built-in importers, by engine id
IMPORTERS = {c.engine_id: c for c in (AltoImporter, PageXmlImporter, HocrImporter, TextImporter, DoclingImporter,
                                       HtmlImporter, AutoImporter)}
