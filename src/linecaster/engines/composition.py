"""Composition step engines: the document of a page or of an item, rendered from its annotation sets."""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from ..data.transcription import Transcription
from .base import RuleEngine


class LinkedCompositionEngine(RuleEngine):
    """Composes a page's or an item's document (``linecaster.document``) from its regions, paragraphs or lines, and
    tables, following the continuation links.

    The document is built by ``linecaster.document.DocumentBuilder`` under the rendering policy: a block per region by
    its content role (titles and headings at their levels, paragraphs, list items, captions, notes, page headers and
    footers in the furniture layer), tables by the policy's table rules, formulas, pictures with the image and the
    text read inside them, optionally sections. A text region is composed from its paragraphs when a recomposition
    made them (a block per paragraph), else from its lines as laid out (a block per region, one row per line:
    diplomatic composition); a paragraph or region that continues another (its ``continues`` link, on the same or an
    earlier page) is one block with it.

    Composition is a rendering: a call adds nothing to the annotation sets it reads (no annotator, no annotation).
    The page unit is the call; an item's document (all its pages, in order) is ``item_document``.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "composition.linked.v1"
    step = "composition"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["document"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        sections: bool = Field(False, description="every title or heading opens a section up to the next one")

    def __call__(self, t: Transcription, name: str = "page", width: int | None = None, height: int | None = None,
                 policy=None, **options):
        """The page's document, named ``name`` (the page id); ``width`` and ``height``: the page image's size (else
        the transcription's source's); ``policy``: the rendering policy (default: the default policy)."""
        from ..data.policy import DEFAULT_POLICY
        from ..document import build_document

        o = self.configured(options)
        return build_document(t, name, width, height, sections=o.sections, policy=policy or DEFAULT_POLICY)

    def item_document(self, pages: list[Transcription], name: str, page_ids: list[str] | None = None,
                      sizes: list[tuple[int | None, int | None]] | None = None, policy=None, **options):
        """One item's document from its pages in order (page ``n`` = the ``n``-th), named ``name`` (the item id).
        ``page_ids`` are the pages' ids, as references to other pages name them (``<page_id>#<id>``), ``sizes``
        their images' (width, height)."""
        from ..data.policy import DEFAULT_POLICY
        from ..document import DocumentBuilder

        o = self.configured(options)
        b = DocumentBuilder(name, sections=o.sections, policy=policy or DEFAULT_POLICY)
        for k, t in enumerate(pages):
            w, h = sizes[k] if sizes else (None, None)
            b.add_page(t, w, h, page_id=page_ids[k] if page_ids else None)
        return b.build()
