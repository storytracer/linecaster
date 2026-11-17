"""``Composer``: the document of a page or of an item, rendered from its regions, paragraphs or lines, and tables
(``composition.*`` engines; ``composition.linked.v1``, ``linecaster.document``).

In the modular pipeline's order: ... recognition -> tables -> ``Typographer`` ->
``Recomposer`` -> ``Composer`` -> writers. Without a ``Recomposer`` the document is diplomatic: each text region as
laid out, one row per line.
"""
from __future__ import annotations

from typing import Any

from linecaster.catalog.registry import DEFAULT_POLICY_REF, rendering_policy
from linecaster.errors import PipelineConfigError
from linecaster.document import COMPOSED_KEY, DOCUMENT_KEY, to_text
from linecaster.core.contract import Contract, Part, parts
from linecaster.core.item import ITEM_KEY, item_pages
from linecaster.core.rule import RuleComponent

UNITS = ("page", "item")


class Composer(RuleComponent):
    """Composes the document (``linecaster.document``) of a page or an item by a composition engine.

    Text regions are composed from their paragraphs when a ``Recomposer`` made them, else from their lines as laid
    out (a diplomatic document). Reads ``regions`` and ``lines`` (and the paragraphs when there are); adds
    ``document``; stat ``documents`` (pages) or ``items``. Composition is a rendering: the transcriptions are left
    as they are (no annotator is added), and the document travels with the page or item record only, it is not
    stored.

    ``unit="page"``: one document per page, named after the page id, in ``doc.metadata["document"]`` (as a dict),
    and the transcription composed in ``doc.metadata["document_transcription"]``, for the page writers (a writer
    without them renders the document itself). ``unit="item"``: one document per item record
    (``linecaster.core.item``), page ``n`` its ``n``-th page, paragraphs continued across pages (an
    item-level ``Recomposer`` before it): ``doc.metadata["document"]`` and ``["item_id"]``, ``doc.text`` its plain
    text (with furniture), as ``ItemDocumentWriter`` writes them.

    Args:
        preset: the composition engine: a preset (e.g. ``linked-composition``) or an ``InProcess`` engine spec.
        transcription: the transcription to compose.
        unit: ``page`` (a document per page) or ``item`` (a document per item record, after a ``Binder``).
        options: engine options over the preset's, e.g. ``{"sections": True}``; ``None``: the preset's.
        policy: the rendering policy (a catalog ``policy`` entry) that puts each region into its layer.

    Example:
        Composer("linked-composition")
        Composer("linked-composition", unit="item")
    """

    name = "composer"
    step = "composition"
    docs_args = {"preset": "linked-composition"}

    def __init__(self, preset, transcription: str = "ocr_new", unit: str = "page",
                 options: dict[str, Any] | None = None, policy: str = DEFAULT_POLICY_REF):
        if unit not in UNITS:
            raise PipelineConfigError(f"composer: unit {unit!r}; choose {', '.join(UNITS)}")
        self.unit, self.policy = unit, policy
        super().__init__(preset, transcription, options)
        rendering_policy(policy)                      # an unknown policy fails at construction

    def contract(self) -> Contract:
        """It reads the regions and lines (and the paragraphs when there are: they are optional, so not named)."""
        reads = parts(("regions", "lines"), self.transcription)
        adds = parts(("document",), self.transcription) if self.unit == "page" else frozenset({Part("document")})
        return Contract(unit=self.unit, kind=self.kind, reads=reads, adds=adds)

    def process_page(self, doc, page):
        t = page.transcriptions.get(self.transcription)
        if t is None:
            self.stat_update("no_transcription")
            return page
        w = page.image.width if page.image else None
        h = page.image.height if page.image else None
        document = self.engine(t, name=page.page_id, width=w, height=h, policy=rendering_policy(self.policy))
        doc.metadata.update({DOCUMENT_KEY: document.model_dump(by_alias=True), COMPOSED_KEY: self.transcription})
        self.stat_update("documents")
        return page

    def run(self, data, rank: int = 0, world_size: int = 1):
        if self.unit == "page":
            yield from super().run(data, rank, world_size)
            return
        for doc in data:
            with self.track_time():
                pages = item_pages(doc)
                item = doc.metadata[ITEM_KEY]["item_id"]
                ts = [p.transcription(self.transcription) for p in pages]
                document = self.engine.item_document(
                    ts, item, page_ids=[p.page_id for p in pages],
                    sizes=[(p.image.width, p.image.height) if p.image else (None, None) for p in pages],
                    policy=rendering_policy(self.policy))
                doc.metadata.update({"item_id": item, DOCUMENT_KEY: document.model_dump(by_alias=True)})
                doc.text = to_text(document, furniture=True)
            self.stat_update("items")
            yield doc
