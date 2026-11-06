"""Page records (everything but the image bytes, plus id and text) on datatrove's writers: ``PageJsonlWriter``,
``PageParquetWriter``, one file per task (``${rank}``) or per item (``${item_id}``)."""
from __future__ import annotations

import json

from datatrove.io import DataFolderLike
from datatrove.pipeline.writers import JsonlWriter, ParquetWriter

from ...data.page import PAGE_KEY, PAGE_SCHEMA
from ..base.contract import Contracted


def page_record(self, doc) -> dict:
    """datatrove adapter: the format (``schema``), ``id``, ``text`` and the page record; errors recorded on the way
    are kept."""
    row = {"schema": PAGE_SCHEMA, "id": doc.id, "text": doc.text, PAGE_KEY: doc.metadata.get(PAGE_KEY)}
    if doc.metadata.get("errors"):
        row["errors"] = doc.metadata["errors"]
    return row


def page_record_json(self, doc) -> dict:
    """Parquet-friendly: the page record as a JSON string (its nested structure varies between steps), and the
    errors as a JSON string or null, so every row has the same columns (``PARQUET_SCHEMA``)."""
    row = page_record(self, doc)
    row[PAGE_KEY] = json.dumps(row[PAGE_KEY], ensure_ascii=False)
    row["errors"] = json.dumps(row["errors"], ensure_ascii=False) if "errors" in row else None
    return row


def parquet_schema():
    """The page records' Parquet columns. Given explicitly: datatrove otherwise takes a file's schema from its first
    row, and a column that row lacks (``errors``) would be dropped from every later row."""
    import pyarrow as pa

    return pa.schema([("schema", pa.string()), ("id", pa.string()), ("text", pa.string()), (PAGE_KEY, pa.string()),
                      ("errors", pa.string())])


class _Flushed:
    """A datatrove writer whose ``close()`` (its files flushed and closed: a remote file is uploaded then) is reported
    to the observers (``flush``, with the files it wrote)."""

    def close(self):
        import time

        start, files = time.time_ns(), len(getattr(self.output_mg, "_output_files", None) or {})
        try:
            return super().close()
        finally:
            self.report("flush", start, files=files)


class PageJsonlWriter(_Flushed, Contracted, JsonlWriter):
    """Writes the page records as JSON Lines, one file per task, or into item shards for a later stage.

    A row per page: ``schema`` (``linecaster.page/2``), ``id``, ``text``, ``page`` (the page record without the
    image bytes) and ``errors`` when a block failed on the page. It reads no part in particular (the whole page
    record). The files' flush is reported to the observers. Pages pass through.

    Args:
        output_folder: the folder (local path, fsspec URI or ``DataFolder``) the records go to.
        output_filename: the file name, datatrove's template (``${rank}``, ``${item_id}``, ...).
        item_shards: the number of item shards: every page goes into its item's shard folder
            (``<shard>/<output_filename>``, ``linecaster.blocks.writers.shards``), so a later stage reads whole
            items; default: no shards.
        **kwargs: datatrove's ``JsonlWriter`` arguments (``compression``, ``max_file_size``, ...).
    """

    name = "🐿 page records (jsonl)"
    role = "writer"            # the whole page record: no part in particular
    docs_args = {"output_folder": "out/pages"}

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


class PageParquetWriter(_Flushed, Contracted, ParquetWriter):
    """Writes the page records as Parquet, one file per task.

    The columns are fixed (``parquet_schema``): ``schema``, ``id``, ``text``, ``page`` (the page record as a JSON
    string) and ``errors`` (a JSON string, or null), so every row has the same columns. It reads no part in
    particular. The files' flush is reported to the observers. Pages pass through.

    Args:
        output_folder: the folder (local path, fsspec URI or ``DataFolder``) the records go to.
        output_filename: the file name, datatrove's template (``${rank}``, ...).
        **kwargs: datatrove's ``ParquetWriter`` arguments (``compression``, ``batch_size``, ``max_file_size``, ...;
            ``schema`` defaults to the page records' columns).
    """

    name = "📒 page records (parquet)"
    role = "writer"
    docs_args = {"output_folder": "out/pages"}

    def __init__(self, output_folder: DataFolderLike, output_filename: str = "${rank}.parquet", **kwargs):
        kwargs.setdefault("schema", parquet_schema())
        super().__init__(output_folder, output_filename, adapter=page_record_json, **kwargs)
