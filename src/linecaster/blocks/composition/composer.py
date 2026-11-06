"""``Composer``: the document of a page (the transcription's ``docling`` part) or of an item, from its regions,
paragraphs or lines, and tables (``composition.*`` engines; ``composition.docling.v1``, ``linecaster.formats.
docling``).

In squiddleocr's order: ... recognition -> ``UnicodeNormalizer`` -> tables -> ``Typographer`` -> ``Recomposer``
-> ``Composer`` -> writers. Without a ``Recomposer`` the document is diplomatic: each text region as laid out, one
row per line (squiddleocr's ``--text lines``).
"""
from __future__ import annotations

from typing import Any

from ...errors import PipelineConfigError
from ...formats.docling import REGION_MAP_KEY, docling_dict, to_text
from ..base.contract import Contract, Part, parts
from ..base.item import ITEM_KEY, item_pages, set_item_pages
from ..base.rule import RuleBlock, now, stamp

UNITS = ("page", "item")


class Composer(RuleBlock):
    """The DoclingDocument of the named transcription by a composition engine (``preset``: e.g.
    ``docling-composition@1``, or an ``InProcess`` engine spec; ``options`` over it, e.g. ``{"sections": True}``):
    text regions from their paragraphs when a ``Recomposer`` made them, else from their lines as laid out.

    ``unit="page"``: one document per page, named after the page id, in the transcription's ``docling``; the map
    from each Docling item to its layout region (``"<page_no>:<region id>"``) in
    ``transcription.extra["docling_region_of"]``, for the Markdown dividers of the page writers.
    ``unit="item"``: one document per item record (``linecaster.blocks.base.item``), page ``n`` its ``n``-th
    page, paragraphs continued across pages (an item-level ``Recomposer`` before it): ``doc.metadata["docling"]``,
    ``["region_of"]`` and ``["item_id"]``, ``doc.text`` its plain text (with furniture), as ``ItemDocumentWriter``
    writes them."""

    name = "composer"
    step = "composition"
    REGION_MAP = REGION_MAP_KEY

    def __init__(self, preset, transcription: str = "ocr_new", unit: str = "page",
                 options: dict[str, Any] | None = None):
        if unit not in UNITS:
            raise PipelineConfigError(f"composer: unit {unit!r}; choose {', '.join(UNITS)}")
        self.unit = unit
        super().__init__(preset, transcription, options)

    def contract(self) -> Contract:
        """It reads the regions and lines (and the paragraphs when there are: they are optional, so not named)."""
        reads = parts(("regions", "lines"), self.transcription)
        adds = parts(("document",), self.transcription) if self.unit == "page" else frozenset({Part("document")})
        return Contract(unit=self.unit, role=self.role, reads=reads, adds=adds)

    def apply(self, page, t) -> None:
        w = page.image.width if page.image else None
        h = page.image.height if page.image else None
        self.engine(t, name=page.page_id, width=w, height=h)
        self.stat_update("documents")

    def run(self, data, rank: int = 0, world_size: int = 1):
        if self.unit == "page":
            yield from super().run(data, rank, world_size)
            return
        for doc in data:
            with self.track_time():
                pages = item_pages(doc)
                item = doc.metadata[ITEM_KEY]["item_id"]
                ts = [p.transcription(self.transcription) for p in pages]
                start, began = now()
                n = [len(t.steps) for t in ts]
                document, region_of = self.engine.item_document(
                    ts, item, page_ids=[p.page_id for p in pages],
                    sizes=[(p.image.width, p.image.height) if p.image else (None, None) for p in pages])
                for t, k in zip(ts, n):
                    for info in t.steps[k:]:
                        stamp(info, self.backend, start, began)
                set_item_pages(doc, pages)
                doc.metadata.update(item_id=item, docling=docling_dict(document), region_of=region_of)
                doc.text = to_text(document, furniture=True)
            self.stat_update("items")
            yield doc
