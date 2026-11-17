"""``MediaWikiImporter`` (``import.mediawiki.v1``): a ProofreadPage ``Page:`` page's revision read into a
transcription, through wikitextprocessor in the wiki's own context (``PageReader``).

The source document's content is the revision's wikitext; its ``context`` gives the page's title (``title``, else the
document's ``record``) and, where known, where its header ends and its footer starts (``header_end``,
``footer_start``; else ProofreadPage's stored form says it). The options name the wiki (``site``: a folder written by
``linecaster-mediawiki intake``) and its conventions (``conventions``: a catalog entry, by its ``id``).
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from linecaster.engines.api import Importer, conventions as catalog_conventions

from linecaster_mediawiki.reader import PageReader
from linecaster_mediawiki.site import Site


class MediaWikiImporter(Importer):
    """A Page: page's wikitext, read through wikitextprocessor under a wiki's conventions.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "import.mediawiki.v1"
    step: ClassVar[str] = "import"
    format: ClassVar[str] = "mediawiki"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["regions", "reading_order", "lines", "text"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(Importer.Options):
        site: str | None = Field(None, description="the wiki: a folder written by linecaster-mediawiki intake")
        conventions: str | None = Field(None, description="the wiki's conventions, a catalog entry (its id)")

    def __init__(self, **options):
        super().__init__(**options)
        self._readers: dict[tuple, PageReader] = {}

    def reader(self, options) -> PageReader:
        """The page reader of a site and conventions, made once."""
        if not options.site:
            raise ValueError("import.mediawiki.v1: the option site (a folder written by linecaster-mediawiki intake) "
                             "is required")
        key = (options.site, options.conventions)
        if key not in self._readers:
            c = catalog_conventions(options.conventions) if options.conventions else None
            self._readers[key] = PageReader(Site(options.site), c)
        return self._readers[key]

    def read(self, source, options):
        ctx = source.context
        title = ctx.get("title") or source.record
        if not title:
            raise ValueError("import.mediawiki.v1: the document needs its page's title (context title, or record)")
        parts = (int(ctx["header_end"]), int(ctx["footer_start"])) if ctx.get("header_end") is not None \
            and ctx.get("footer_start") is not None else None
        r = self.reader(options).read(source.as_text(), title, revision=source.revision, record=source.record,
                                      dataset=source.dataset, parts=parts)
        t = r.transcription
        rules = next(i for i, a in enumerate(t.annotators) if a.kind == "rule")
        t.annotators[rules].settings = options.model_dump(mode="json")
        return t
