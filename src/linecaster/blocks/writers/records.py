"""Page records (everything but the image bytes, plus id and text) on datatrove's writers: ``PageJsonlWriter``,
``PageParquetWriter``, one file per task (``${rank}``) or per item (``${item_id}``)."""
from __future__ import annotations

import json

from datatrove.io import DataFolderLike
from datatrove.pipeline.writers import JsonlWriter, ParquetWriter

from ...data.page import PAGE_KEY


def page_record(self, doc) -> dict:
    """datatrove adapter: ``id``, ``text`` and the page record; errors recorded on the way are kept."""
    row = {"id": doc.id, "text": doc.text, PAGE_KEY: doc.metadata.get(PAGE_KEY)}
    if doc.metadata.get("errors"):
        row["errors"] = doc.metadata["errors"]
    return row


def page_record_json(self, doc) -> dict:
    """Parquet-friendly: the page record as a JSON string (its nested structure varies between steps)."""
    row = page_record(self, doc)
    row[PAGE_KEY] = json.dumps(row[PAGE_KEY], ensure_ascii=False)
    if "errors" in row:
        row["errors"] = json.dumps(row["errors"], ensure_ascii=False)
    return row


class PageJsonlWriter(JsonlWriter):
    """Page records as JSON Lines. With ``item_shards`` every page goes into its item's shard folder
    (``<shard>/${rank}.jsonl.gz``, ``linecaster.blocks.writers.shards``), for a later stage that reads whole items."""

    name = "🐿 page records (jsonl)"

    def __init__(self, output_folder: DataFolderLike, output_filename: str = "${rank}.jsonl.gz",
                 item_shards: int | None = None, **kwargs):
        if item_shards:
            from .shards import SHARD_KEY

            output_filename = f"${{{SHARD_KEY}}}/{output_filename}"
        super().__init__(output_folder, output_filename, adapter=page_record, **kwargs)
        self.item_shards = item_shards

    def write(self, document, rank: int = 0, **kwargs):
        if self.item_shards:
            from ..base.page import page_of
            from .shards import SHARD_KEY, item_shard

            page = page_of(document)
            document.metadata[SHARD_KEY] = item_shard(page.item_id or document.id, self.item_shards)
        return super().write(document, rank, **kwargs)


class PageParquetWriter(ParquetWriter):
    name = "📒 page records (parquet)"

    def __init__(self, output_folder: DataFolderLike, output_filename: str = "${rank}.parquet", **kwargs):
        super().__init__(output_folder, output_filename, adapter=page_record_json, **kwargs)
