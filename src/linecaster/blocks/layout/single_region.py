"""Layout blocks without a model.

``SingleRegionLayout``: no layout analysis, the whole page is one ``text`` region (plain OCR; what
squiddleocr's ``--layout none`` does). A line step on the whole page and ``LineAssigner``
then put every line into it; no table or formula regions exist.
"""
from __future__ import annotations

from ...data.geometry import BBox
from ...data.page import Page
from ...data.transcription import Region
from ...errors import PageError
from ..base.page import PageBlock


class SingleRegionLayout(PageBlock):
    """Replace the transcription's regions with one region covering the page image (id ``page``,
    label ``text``, reading order 0)."""

    name = "single region layout"
    parts_read = ("metadata",)
    parts_added = ("regions", "reading_order")

    def __init__(self, transcription: str = "ocr_new", label: str = "text", region_id: str = "page"):
        super().__init__()
        self.transcription, self.label, self.region_id = transcription, label, region_id

    def process_page(self, doc, page: Page) -> Page:
        if page.image is None or not page.image.width or not page.image.height:
            raise PageError(page.page_id, type(self).__name__, "no image size")
        t = page.transcription(self.transcription)
        b = BBox(0.0, 0.0, float(page.image.width), float(page.image.height))
        t.regions = [Region(id=self.region_id, label=self.label, polygon=b.polygon.tolist(),
                            bbox=[0.0, 0.0, b.width, b.height], score=1.0, reading_order=0)]
        return page
