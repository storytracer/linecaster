"""``RecipeStamper``: the recipe edition a run followed, on every step of every page (``ModelInfo.recipe``).

``linecaster.runtime.run.main`` puts it before the first writer when a run follows a recipe (``--recipe``), so the
page records and every ALTO, PAGE-XML and hOCR file name the recipe edition and its hash next to each preset.
"""
from __future__ import annotations

from ..base.page import PageBlock


class RecipeStamper(PageBlock):
    name = "recipe stamper"

    def __init__(self, recipe: str, recipe_sha256: str):
        super().__init__()
        self.recipe, self.recipe_sha256 = recipe, recipe_sha256

    def process_page(self, doc, page):
        for t in page.transcriptions.values():
            for m in t.model:
                m.recipe, m.recipe_sha256 = self.recipe, self.recipe_sha256
        return page
