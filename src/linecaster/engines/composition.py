"""Composition step engines: the document of a page (``Transcription.docling``) or of an item."""
from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from ..data.transcription import Transcription
from .base import RuleEngine


class DoclingCompositionEngine(RuleEngine):
    """Composes a page's DoclingDocument from its regions, paragraphs or lines, and tables.

    The document is built by ``linecaster.formats.docling.DocumentBuilder``: titles and section headers at their heading
    levels, text items with Docling's labels, page headers and footers in the furniture layer, tables with their cells,
    formulas, pictures with the text read inside them, optionally one section group per heading; the map of items to
    regions in ``extra["docling_region_of"]``. A text region is composed from its paragraphs when a recomposition made
    them (one item per paragraph, continued paragraphs in one item), else from its lines as laid out (one item per
    region, one row per line: diplomatic composition).

    The page unit is the call (the document in ``Transcription.docling``); an item's document (all its pages, in
    order, paragraphs continued across pages) is ``item_document``. Each call records a ``StepInfo``.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "composition.docling.v1"
    step = "composition"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["document"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        sections: bool = Field(False, description="every heading opens a section group up to the next heading")

    def __call__(self, t: Transcription, name: str = "page", width: int | None = None, height: int | None = None,
                 **options) -> Transcription:
        """The page's document, named ``name`` (the page id); ``width`` and ``height``: the page image's size
        (else the transcription's source's)."""
        from ..formats.docling import REGION_MAP_KEY, DocumentBuilder, docling_dict

        o = self.configured(options)
        b = DocumentBuilder(name, sections=o.sections)
        b.add_page(t, width, height)
        t.docling = docling_dict(b.build())
        t.extra[REGION_MAP_KEY] = dict(b.region_of)
        t.steps.append(self.step_info(o))
        return t

    def item_document(self, pages: list[Transcription], name: str, page_ids: list[str] | None = None,
                      sizes: list[tuple[int | None, int | None]] | None = None,
                      **options) -> tuple[Any, dict[str, str]]:
        """One item's document from its pages in order (page ``n`` = the ``n``-th), named ``name`` (the item id):
        the DoclingDocument and the map of its items to ``"<page_no>:<region id>"``. ``page_ids`` are
        the pages' ids as the recomposition named them (``ParagraphRef.page_id``), ``sizes`` their images'
        (width, height). Each page records the step."""
        from ..formats.docling import DocumentBuilder

        o = self.configured(options)
        b = DocumentBuilder(name, sections=o.sections)
        for k, t in enumerate(pages):
            w, h = sizes[k] if sizes else (None, None)
            b.add_page(t, w, h, page_id=page_ids[k] if page_ids else None)
        doc = b.build()
        for t in pages:
            t.steps.append(self.step_info(o))
        return doc, dict(b.region_of)
