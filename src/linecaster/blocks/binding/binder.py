"""``Binder``: page records -> item records (``linecaster.blocks.base.item``), each item's pages in order."""
from __future__ import annotations

from datatrove.pipeline.base import PipelineStep

from ..base.contract import Contract, Contracted
from ..base.item import gather, new_item_document


class Binder(Contracted, PipelineStep):
    """Binds each item's page records, in order, into one item record.

    The item record is one datatrove document (``doc.id`` the item id, ``doc.metadata["item"]``,
    ``linecaster.blocks.base.item``) holding its pages in order (``Page.sequence``, then page id); a page without an
    item is an item of its own. The item-unit blocks after it (``Recomposer``, ``CharacterNormalizer`` and
    ``Composer`` with ``unit="item"``) and the item writers read it; the ``Splitter`` turns it back into pages. It
    changes the stream's unit from pages to items and touches no part: the item record holds its pages as they
    came, every transcription with every part (the builder's checks carry them past the binder), but not the page
    images' bytes.

    **A task must see whole items**: linecaster's run layout buckets page records by item (one item in one file),
    and the pages of an item must arrive in one task (with several tasks the builder cuts the pipeline here: the
    page records in item shards, then a stage over whole shards). An item is emitted once all its pages have
    arrived (when its pages' metadata give the count) or when the input ends (stat ``incomplete_items``: items the
    input ended in before their count).

    Args:
        count_key: the page metadata key that holds the item's page count; a page without it waits for the end
            of the input.
    """

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
