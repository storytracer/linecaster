"""``Splitter``: item records -> their page records, in order."""
from __future__ import annotations

from datatrove.data import Document
from datatrove.pipeline.base import PipelineStep

from ..base.contract import Contract, Contracted
from ..base.item import ITEM_KEY, item_pages
from ..base.page import set_page


class Splitter(Contracted, PipelineStep):
    """The pages of each item record (``linecaster.blocks.base.item``), in the item's order, each a page document
    again (``doc.id`` the page id, ``doc.metadata["page"]``, ``doc.text`` the text of ``primary``) carrying what the
    item-level blocks added to it: the paragraphs of an item-level ``Recomposer`` (continued across pages, the
    references naming the other page), the normalized texts, the step records. The item's own parts (its
    document) stay with the item; the pages carry no image bytes (``PageRecordReader`` fetches them again by URI)."""

    type = "🔠 - LINECASTER"
    name = "📄 splitter"
    role = "splitter"

    def __init__(self, primary: str = "ocr_new"):
        super().__init__()
        self.primary = primary

    def contract(self) -> Contract:
        return Contract(unit="item", unit_out="page", role=self.role)

    def run(self, data, rank: int = 0, world_size: int = 1):
        for doc in data:
            if ITEM_KEY not in doc.metadata:
                self.stat_update("no_item")
                continue
            self.stat_update("items")
            for page in item_pages(doc):
                out = Document(text="", id=page.page_id, metadata={})
                set_page(out, page, self.primary)
                self.stat_update("pages")
                yield out
