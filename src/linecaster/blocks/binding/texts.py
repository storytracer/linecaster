"""``ItemTexts``: page records -> one text per item and variant (``linecaster.text.variants``).

Input pages may come in any order but an item's pages must all be in one input file (linecaster's
run layout buckets files by item). An item is emitted once all its pages have arrived
(``page.metadata["item_page_count"]`` when the page list gave it) or when the input ends. For each
item and variant one ``Document``: ``id`` = item id, ``text`` = the variant, metadata ``item_id``,
``variant``, ``fidelity``, ``flow``, ``scope``, ``format``, ``page_ids``, ``pages`` (count) and
``token_count`` when a ``token_counter`` is given (e.g. a tiktoken encoding's ``encode`` length).
Write with ``output_filename="${variant}/${rank}.parquet"`` to get one folder per variant.
"""
from __future__ import annotations

from collections.abc import Callable

from datatrove.data import Document
from datatrove.pipeline.base import PipelineStep

from ...data.page import Page
from ...data.transcription import Transcription
from ...errors import PipelineConfigError
from ...text.variants import VARIANTS, variants
from ..base.contract import Contract, Contracted, Part, parts
from ..base.page import page_of


class ItemTexts(Contracted, PipelineStep):
    type = "🔠 - LINECASTER"
    name = "📚 item texts"
    role = "binder"

    def contract(self) -> Contract:
        return Contract(unit="page", unit_out="item", role=self.role, reads=parts(("text",), self.transcription),
                        adds=frozenset({Part("text")}))

    def __init__(self, transcription: str = "ocr_new", variants: tuple[str, ...] = tuple(VARIANTS),
                 token_counter: Callable[[str], int] | None = None, count_key: str = "item_page_count"):
        super().__init__()
        unknown = set(variants) - set(VARIANTS)
        if unknown:
            raise PipelineConfigError(f"unknown variants {sorted(unknown)}; known: {sorted(VARIANTS)}")
        self.transcription, self.variants, self.token_counter, self.count_key = \
            transcription, tuple(variants), token_counter, count_key

    def _emit(self, item: str, pages: list[Page]):
        pages = sorted(pages, key=lambda p: (p.sequence is None, p.sequence or 0, p.page_id))
        ts = [p.transcriptions.get(self.transcription) or Transcription() for p in pages]
        texts = variants(ts)
        for variant in self.variants:
            fidelity, flow, scope, fmt = VARIANTS[variant]
            text = texts[variant]
            meta = {"item_id": item, "variant": variant, "fidelity": fidelity, "flow": flow, "scope": scope,
                    "format": fmt, "page_ids": [p.page_id for p in pages], "pages": len(pages)}
            if self.token_counter is not None:
                meta["token_count"] = self.token_counter(text)
            self.stat_update(f"{variant}_chars", value=len(text))
            yield Document(text=text, id=item, metadata=meta)
        self.stat_update("items")

    def run(self, data, rank: int = 0, world_size: int = 1):
        items: dict[str, list[Page]] = {}
        for doc in data:
            page = page_of(doc)
            self.stat_update("pages")
            item = page.item_id or doc.id
            items.setdefault(item, []).append(page)
            expected = page.metadata.get(self.count_key)
            if expected and len(items[item]) >= expected:
                yield from self._emit(item, items.pop(item))
        for item, pages in items.items():
            if any(p.metadata.get(self.count_key) for p in pages):
                self.stat_update("incomplete_items")
            yield from self._emit(item, pages)
