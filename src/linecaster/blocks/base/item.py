"""Item records in a stream: one datatrove ``Document`` per item, its pages in order.

``doc.id`` is the item id and ``doc.metadata["item"]`` the item record: ``{"item_id": ..., "pages": [...]}``, the
page records (``Page`` as JSON-compatible dicts) in sequence order. The ``Binder`` makes it; the item-unit blocks
(``Recomposer``, ``CharacterNormalizer`` and ``Composer`` with ``unit="item"``) read and extend it; a ``Composer``
adds the item's document next to it (``doc.metadata["docling"]``, ``["region_of"]``, ``["item_id"]``), which the
``ItemDocumentWriter`` writes; the ``ItemTextWriter`` renders the text variants from its pages; the ``Splitter``
passes its pages on as page documents.

``gather`` collects a page stream into items: a task must see whole items (linecaster's run layout buckets page
records by item, one item in one file), and an item is complete once all its pages have arrived
(``page.metadata[count_key]``, when the page list gave the count) or when the input ends.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator

from datatrove.data import Document

from ...data.page import Page
from .page import page_of

#: where an item document keeps its item record
ITEM_KEY = "item"


def in_order(pages: list[Page]) -> list[Page]:
    """An item's pages in sequence order (pages without a sequence last), then by page id."""
    return sorted(pages, key=lambda p: (p.sequence is None, p.sequence or 0, p.page_id))


def new_item_document(item_id: str, pages: list[Page]) -> Document:
    """The item document of ``pages`` (put in order)."""
    doc = Document(text="", id=item_id, metadata={})
    set_item_pages(doc, in_order(pages), item_id)
    return doc


def item_pages(doc: Document) -> list[Page]:
    return [Page.model_validate(p) for p in doc.metadata[ITEM_KEY]["pages"]]


def set_item_pages(doc: Document, pages: list[Page], item_id: str | None = None) -> None:
    record = doc.metadata.get(ITEM_KEY) or {}
    doc.metadata[ITEM_KEY] = {"item_id": item_id or record.get("item_id") or doc.id,
                              "pages": [p.record() for p in pages]}


def gather(data: Iterable[Document], block, count_key: str = "item_page_count") -> Iterator[tuple[str, list[Page]]]:
    """``(item id, its pages in order)`` from a page stream, each item as soon as it is complete; ``block`` counts
    ``pages`` and ``incomplete_items`` (items the input ended in before their count)."""
    items: dict[str, list[Page]] = {}
    for doc in data:
        page = page_of(doc)
        block.stat_update("pages")
        item = page.item_id or doc.id
        items.setdefault(item, []).append(page)
        expected = page.metadata.get(count_key)
        if expected and len(items[item]) >= expected:
            yield item, in_order(items.pop(item))
    for item, pages in items.items():
        if any(p.metadata.get(count_key) for p in pages):
            block.stat_update("incomplete_items")
        yield item, in_order(pages)
