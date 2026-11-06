"""``Binder``: page records -> item records (``linecaster.blocks.base.item``), each item's pages in order."""
from __future__ import annotations

from datatrove.pipeline.base import PipelineStep

from ..base.contract import Contract, Contracted
from ..base.item import gather, new_item_document


class Binder(Contracted, PipelineStep):
    """One item record per item: its page records in order (``Page.sequence``, then page id), as one datatrove
    document (``doc.id`` the item id, ``doc.metadata["item"]``). The item-unit blocks after it (``Recomposer`` and
    ``Composer`` with ``unit="item"``, ``CharacterNormalizer(unit="item")``) and the item writers read it; the
    ``Splitter`` turns it back into pages.

    The item record holds its pages as they came, every transcription with every part (the builder's checks carry
    them past the binder), but not the page images' bytes.

    **A task must see whole items**: linecaster's run layout buckets page records by item (one item in one file),
    and the pages of an item must arrive in one task (with several tasks the builder cuts the pipeline here: the
    page records in item shards, then a stage over whole shards). An item is emitted once all its pages have
    arrived (``page.metadata[count_key]``, when the page list gave the count) or when the input ends (stat
    ``incomplete_items``: items the input ended in before their count)."""

    type = "🔠 - LINECASTER"
    name = "📚 binder"
    role = "binder"

    def __init__(self, count_key: str = "item_page_count"):
        super().__init__()
        self.count_key = count_key

    def contract(self) -> Contract:
        return Contract(unit="page", unit_out="item", role=self.role)

    def run(self, data, rank: int = 0, world_size: int = 1):
        for item, pages in gather(data, self, self.count_key):
            with self.track_time():
                doc = new_item_document(item, pages)
            self.stat_update("items")
            yield doc
