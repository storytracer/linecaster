"""``Composer``: the document of a page or of an item, rendered from its regions, paragraphs or lines, and tables
(``composition.*`` engines; ``composition.docling.v1``, ``linecaster.formats.docling``).

In the modular pipeline's order: ... recognition -> ``UnicodeNormalizer`` -> tables -> ``Typographer`` ->
``Recomposer`` -> ``Composer`` -> writers. Without a ``Recomposer`` the document is diplomatic: each text region as
laid out, one row per line.
"""
from __future__ import annotations

from typing import Any

from ...catalog.registry import DEFAULT_POLICY_REF, rendering_policy
from ...errors import PipelineConfigError
from ...formats.docling import COMPOSED_KEY, DOCUMENT_KEY, REGION_MAP_KEY, docling_dict, to_text
from ..base.contract import Contract, Part, parts
from ..base.item import ITEM_KEY, item_pages
from ..base.rule import RuleBlock

UNITS = ("page", "item")


class Composer(RuleBlock):
    """Composes the DoclingDocument of a page or an item by a composition engine.

    Text regions are composed from their paragraphs when a ``Recomposer`` made them, else from their lines as laid
    out (a diplomatic document). Reads ``regions`` and ``lines`` (and the paragraphs when there are); adds
    ``document``; stat ``documents`` (pages) or ``items``. Composition is a rendering: the transcriptions are left
    as they are (no annotator is added), and the document travels with the page or item record only, it is not
    stored.

    ``unit="page"``: one document per page, named after the page id, in ``doc.metadata["docling"]``, the map from
    each Docling item to its layout region (``"<page_no>:<region id>"``) in ``doc.metadata["region_of"]`` and the
    transcription composed in ``doc.metadata["docling_transcription"]``, for the page writers (a writer without
    them renders the document itself). ``unit="item"``: one document per item record
    (``linecaster.blocks.base.item``), page ``n`` its ``n``-th page, paragraphs continued across pages (an
    item-level ``Recomposer`` before it): ``doc.metadata["docling"]``, ``["region_of"]`` and ``["item_id"]``,
    ``doc.text`` its plain text (with furniture), as ``ItemDocumentWriter`` writes them.

    Args:
        preset: the composition engine: a preset (e.g. ``docling-composition@1``) or an ``InProcess`` engine spec.
        transcription: the transcription to compose.
        unit: ``page`` (a document per page) or ``item`` (a document per item record, after a ``Binder``).
        options: engine options over the preset's, e.g. ``{"sections": True}``; ``None``: the preset's.
        policy: the rendering policy (a catalog ``policy`` edition) that puts each region into its layer.

    Example:
        Composer("docling-composition@1")
        Composer("docling-composition@1", unit="item")
    """

    name = "composer"
    step = "composition"
    REGION_MAP = REGION_MAP_KEY
    docs_args = {"preset": "docling-composition@1"}

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
        return Contract(unit=self.unit, role=self.role, reads=reads, adds=adds)

    def process_page(self, doc, page):
        t = page.transcriptions.get(self.transcription)
        if t is None:
            self.stat_update("no_transcription")
            return page
        w = page.image.width if page.image else None
        h = page.image.height if page.image else None
        document, region_of = self.engine(t, name=page.page_id, width=w, height=h,
                                          policy=rendering_policy(self.policy))
        doc.metadata.update({DOCUMENT_KEY: docling_dict(document), REGION_MAP_KEY: region_of,
                             COMPOSED_KEY: self.transcription})
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
                document, region_of = self.engine.item_document(
                    ts, item, page_ids=[p.page_id for p in pages],
                    sizes=[(p.image.width, p.image.height) if p.image else (None, None) for p in pages],
                    policy=rendering_policy(self.policy))
                doc.metadata.update({"item_id": item, DOCUMENT_KEY: docling_dict(document),
                                     REGION_MAP_KEY: region_of})
                doc.text = to_text(document, furniture=True)
            self.stat_update("items")
            yield doc
