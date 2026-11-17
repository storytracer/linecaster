"""The import step: engines that read a source document (``linecaster.data.SourceDocument``) into a transcription,
in the pipeline's process.

An importer (``Importer``) is a rule-based engine of step ``import``: ``__call__(source, **options)`` for its unit
``page`` (an item-unit importer takes the item's documents and returns a transcription per page). The base does
what every importer shares: the options (``ground_truth``: the source is a ground truth, read by people), the
source's fields on the transcription (record, revision, dataset, URI), the importer's own annotator (kind ``rule``,
step ``import``: who read the file, with its options; the people or file that made the content are annotators of
their own), and the fit to the page image (a transcription whose coordinates refer to an image of another size is
scaled to the page's). The formats themselves
are ``linecaster.formats``; the importers are thin.

Built in: ``import.alto.v1``, ``import.page.v1``, ``import.hocr.v1``, ``import.text.v1``, ``import.docling.v1``,
``import.html.v1`` (with a source's ``conventions``), ``import.tei.v1`` (one page of a TEI P5 document),
``import.iiif.v1`` (an IIIF annotation page), ``import.omnidocbench.v1`` (a page of OmniDocBench's ground truth) and
``import.auto.v1`` (tells ALTO, PAGE-XML, hOCR, TEI, IIIF annotation
pages and text apart and reads each with its importer). Engine
packages add importers for formats that need more (a wiki's wikitext: ``linecaster-mediawiki``).
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from ..data.source import SourceDocument
from ..data.transcription import Annotator, Transcription
from ..data.writing import language_tag
from .base import RuleEngine

#: the context keys that state a page's writing system
WRITING = ("language", "script", "direction")


class Importer(RuleEngine):
    """Base of the importers. A subclass states ``engine_id``, ``format`` and ``Options``, and implements
    ``read(source, options)``.

    A source document's ``context`` may state the page's writing system (``language``, a BCP 47 tag; ``script``, an
    ISO 15924 code; ``direction``, one of ``linecaster.data.writing.DIRECTIONS``), as a line-level dataset's columns
    do: each becomes the page's classification by the importer, where the file records none of its own; a value that
    is none is a ``ValueError``."""

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
        if not any(a.kind == "rule" and a.step == "import" for a in t.annotators):
            t.add_annotator(self.annotator(o))            # who read the file: the importer, with its options
        stated = {k: source.context[k] for k in WRITING if source.context.get(k) not in (None, "")}
        if stated:
            importer = next(i for i, a in enumerate(t.annotators) if a.kind == "rule" and a.step == "import")
            for scheme, value in stated.items():
                value = str(value).strip()
                if scheme == "language":
                    value = language_tag(value) or value      # en_US as en-US; an ill-formed one fails below
                if t.classification("", scheme) is None:
                    t.classify(importer, "", scheme, value)
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
    """Plain text: a line per line, no geometry; or, with ``line_image``, the text of an image of one line (a
    line-level dataset's row: a page whose one line is the whole image).

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "import.text.v1"
    step: ClassVar[str] = "import"
    format: ClassVar[str] = "text"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["reading_order", "lines", "text"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(Importer.Options):
        line_image: bool = Field(False, exclude_if=lambda v: not v,
                                 description="the text is an image's one line: the page is the line, its box the "
                                             "whole image (a line-level dataset)")

    def read(self, source, options):
        from ..formats.text import from_text

        return from_text(source.data, uri=source.uri, ground_truth=options.ground_truth,
                         line_image=getattr(options, "line_image", False), image_width=source.image_width,
                         image_height=source.image_height)


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
    """HTML, by HTML's semantics and a source's conventions (``conventions``: a catalog entry, ``id``).

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "import.html.v1"
    step: ClassVar[str] = "import"
    format: ClassVar[str] = "html"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["regions", "reading_order", "lines", "text"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(Importer.Options):
        conventions: str | None = Field(None, description="the source's conventions, a catalog entry (id)")

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
        # text was decoded already: parsed as the UTF-8 it is encoded in (bytes: by their charset, as a browser)
        parser = lxml_html.HTMLParser(encoding="utf-8") if isinstance(source.data, str) else None
        reading = HtmlConverter(c).read(lxml_html.fromstring(source.as_bytes(), parser=parser), t, people, rules)
        t.annotators[rules].measurements.update({**reading.coverage.measurements(),
                                                 "ends_paragraph": reading.ends_paragraph})
        if reading.ill_formed_languages:
            t.annotators[rules].measurements["ill_formed_languages"] = dict(reading.ill_formed_languages)
        return t


class TeiImporter(Importer):
    """TEI P5 (``linecaster.formats.tei``: a ``sourceDoc``'s surface, or a page of its text with its ``facsimile``'s
    zones or without geometry), one page of the document (``page``), scaled to the page image by the size its surface
    states.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "import.tei.v1"
    step: ClassVar[str] = "import"
    format: ClassVar[str] = "tei"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["regions", "reading_order", "lines", "text"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(Importer.Options):
        page: int | str = Field(1, description="the document's page to read: its number (1-based) among the "
                                               "sourceDoc's surfaces or the text's pages (pb begins one), or the "
                                               "xml:id of its surface or pb")

    def read(self, source, options):
        from ..formats.tei import from_tei

        return from_tei(source.as_bytes(), page=getattr(options, "page", 1), uri=source.uri,
                        ground_truth=options.ground_truth)


class IiifImporter(Importer):
    """IIIF annotation pages (``linecaster.formats.iiif.from_annotation_page``: linecaster's own and other software's
    that follow the same conventions); boxes in percent of the canvas by the page image's size.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "import.iiif.v1"
    step: ClassVar[str] = "import"
    format: ClassVar[str] = "iiif"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["regions", "reading_order", "lines", "text", "words"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    def read(self, source, options):
        from ..formats.iiif import from_annotation_page

        return from_annotation_page(source.as_text(), uri=source.uri, ground_truth=options.ground_truth,
                                    image_width=source.image_width, image_height=source.image_height)


class AutoImporter(Importer):
    """ALTO, PAGE-XML, hOCR, TEI, IIIF annotation pages or text, told apart by the document's format, else by its content (TEI: its first
    page).

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "import.auto.v1"
    step: ClassVar[str] = "import"
    format: ClassVar[str] = "auto"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["regions", "reading_order", "lines", "text"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)
    BY_FORMAT: ClassVar[dict[str, type[Importer]]] = {"alto": AltoImporter, "page": PageXmlImporter,
                                                       "hocr": HocrImporter, "tei": TeiImporter,
                                                       "iiif": IiifImporter, "text": TextImporter}

    def read(self, source, options):
        from ..formats.text import sniff

        fmt = source.format if source.format in self.BY_FORMAT else sniff(source.as_bytes())
        return self.BY_FORMAT[fmt](ground_truth=options.ground_truth).read(source, options)


class OmniDocBenchImporter(Importer):
    """One page of OmniDocBench's ground truth, an entry of its JSON list as JSON.

    ``linecaster.formats.omnidocbench.from_omnidocbench`` reads it: its elements as regions with roles, lines,
    tables, formulas and reading order, its page attributes on the source. It is scaled to the page image by the size
    it states, except where that size is the image's transposed (width for height: the entry's coordinates are the
    image's; the stated size kept as ``omnidocbench__stated_size``). ``linecaster.formats.omnidocbench.entries``
    splits the JSON's list into its pages.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "import.omnidocbench.v1"
    step: ClassVar[str] = "import"
    format: ClassVar[str] = "omnidocbench"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["regions", "reading_order", "lines", "text", "tables",
                                                                 "formulas"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    def read(self, source, options):
        from ..formats.omnidocbench import from_omnidocbench

        t = from_omnidocbench(source.as_text(), ground_truth=options.ground_truth, uri=source.uri)
        w, h = t.source.image_width, t.source.image_height
        if source.image_width and source.image_height and w and h and w != h and (w, h) == (
                source.image_height, source.image_width):
            # a page size stated transposed (width for height) is no other image: its coordinates are the image's
            t.source.omnidocbench__stated_size = [w, h]
            t.source.image_width, t.source.image_height = source.image_width, source.image_height
        return t


#: the built-in importers, by engine id
IMPORTERS = {c.engine_id: c for c in (AltoImporter, PageXmlImporter, HocrImporter, TextImporter, DoclingImporter,
                                       HtmlImporter, TeiImporter, IiifImporter, AutoImporter, OmniDocBenchImporter)}
