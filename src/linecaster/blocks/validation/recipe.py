"""``RecipeStamper``: the recipe edition a run followed, on every step of every page (``StepInfo.recipe``).
The builder (``build(..., recipe=...)``, which ``linecaster.runtime.run.main`` calls for ``--recipe``) puts it before
the first writer, so the page records and every ALTO, PAGE-XML and hOCR file name the recipe edition and its hash
next to each preset. Before an item writer it stamps the pages of each item record.
"""
from __future__ import annotations

from ..base.item import ITEM_KEY, item_pages, set_item_pages
from ..base.page import PageBlock, page_of, set_page


class RecipeStamper(PageBlock):
    """Stamps the recipe edition a run follows on every step of every transcription, of a page or of each page of an
    item record.

    It sets ``StepInfo.recipe`` and ``StepInfo.recipe_sha256`` and adds no part (unit ``any``: pages or item
    records). The builder puts one before the first writer when a run follows a recipe.

    Args:
        recipe: the recipe edition, ``id@edition``.
        recipe_sha256: that edition's hash (``sha256:<hex>``).
    """

    name = "recipe stamper"
    unit = "any"
    docs_args = {"recipe": "squiddle@1", "recipe_sha256": "sha256:" + "0" * 64}

    def __init__(self, recipe: str, recipe_sha256: str):
        super().__init__()
        self.recipe, self.recipe_sha256 = recipe, recipe_sha256

    def process_page(self, doc, page):
        for t in page.transcriptions.values():
            for m in t.steps:
                m.recipe, m.recipe_sha256 = self.recipe, self.recipe_sha256
        return page

    def run(self, data, rank: int = 0, world_size: int = 1):
        for doc in data:
            with self.track_time():
                if ITEM_KEY in doc.metadata:
                    set_item_pages(doc, [self.process_page(doc, p) for p in item_pages(doc)])
                    self.stat_update("items")
                else:
                    set_page(doc, self.process_page(doc, page_of(doc)))
                    self.stat_update("pages")
            yield doc
