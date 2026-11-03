"""Writers for page rows, on top of datatrove's: the page row (everything but the image bytes) plus
id and text, one file per task (``${rank}``) or per item (``${item_id}``) in the output folder."""
from __future__ import annotations

import json

from datatrove.io import DataFolderLike
from datatrove.pipeline.writers import JsonlWriter, ParquetWriter

from ..page import PAGE_KEY


def page_row(self, doc) -> dict:
    """datatrove adapter: ``id``, ``text`` and the page row; errors recorded on the way are kept."""
    row = {"id": doc.id, "text": doc.text, PAGE_KEY: doc.metadata.get(PAGE_KEY)}
    if doc.metadata.get("errors"):
        row["errors"] = doc.metadata["errors"]
    return row


def page_row_json(self, doc) -> dict:
    """Parquet-friendly: the page row as a JSON string (its nested structure varies between steps)."""
    row = page_row(self, doc)
    row[PAGE_KEY] = json.dumps(row[PAGE_KEY], ensure_ascii=False)
    if "errors" in row:
        row["errors"] = json.dumps(row["errors"], ensure_ascii=False)
    return row


class PageJsonlWriter(JsonlWriter):
    name = "🐿 page rows (jsonl)"

    def __init__(self, output_folder: DataFolderLike, output_filename: str = "${rank}.jsonl.gz", **kwargs):
        super().__init__(output_folder, output_filename, adapter=page_row, **kwargs)


class PageParquetWriter(ParquetWriter):
    name = "📒 page rows (parquet)"

    def __init__(self, output_folder: DataFolderLike, output_filename: str = "${rank}.parquet", **kwargs):
        super().__init__(output_folder, output_filename, adapter=page_row_json, **kwargs)
