"""Writers for resources (``linecaster.blocks.readers.resources``): ``ResourceFilesWriter`` writes each copy as served,
``<kind>/<item>/<name>.<ext>``, and ``ResourceRecordWriter`` the fetch records, ``<rank>.jsonl.gz``."""
from __future__ import annotations

import json

from datatrove.io import DataFolderLike
from datatrove.pipeline.base import PipelineStep

from ..base.contract import Contracted


class ResourceFilesWriter(Contracted, PipelineStep):
    """Writes each resource's bytes as they came, one file per resource.

    Files go to ``<output_folder>/<kind>/<item>/<name>.<ext>`` (any fsspec folder), appearing only once whole (a
    local file as ``<name>.part``, then renamed); a resource read back from its copy (``reused``) is not written again.
    The record's ``uri`` then names the copy, its ``source_uri`` where it came from. A resource that failed (no
    bytes) passes through without a file.

    Args:
        output_folder: the folder (local path, fsspec URI or ``DataFolder``) the copies go to (the run folder).
    """

    type = "💽 - WRITER"
    name = "🌐 resource files"
    role = "writer"
    unit = "item"
    docs_args = {"output_folder": "out"}
    parts_replaced = ("metadata",)          # the record's uri names the copy

    def __init__(self, output_folder: DataFolderLike):
        super().__init__()
        self.output_folder = output_folder

    def run(self, data, rank: int = 0, world_size: int = 1):
        from datatrove.io import get_datafolder

        from ..readers.resources import RESOURCE_KEY
        from .images import _write_whole

        out = get_datafolder(self.output_folder)
        for doc in data:
            record = doc.metadata.get(RESOURCE_KEY)
            data_bytes = doc.media[0].media_bytes if doc.media else None
            if record is None or data_bytes is None:
                self.stat_update("skipped_after_error")
                yield doc
                continue
            path = f"{record['kind']}/{record['item']}/{record['name']}.{record.get('ext') or 'bin'}"
            if record.get("reused"):
                self.stat_update("reused")          # its copy is there already
            else:
                with self.track_time():
                    _write_whole(out, path, data_bytes)
                self.stat_update("files")
            record["uri"] = out.resolve_paths(path)
            yield doc


class ResourceRecordWriter(Contracted, PipelineStep):
    """Writes each resource's record (``doc.metadata["resource"]``, with its errors) as a JSON line, to
    ``<output_folder>/<rank>.jsonl.gz``: one file per task, a failed resource included (``error``, ``errors``).

    Args:
        output_folder: the folder (local path, fsspec URI or ``DataFolder``) of the records (``OUT/resources``).
    """

    type = "💽 - WRITER"
    name = "🌐 resource records"
    role = "writer"
    unit = "item"
    docs_args = {"output_folder": "out/resources"}
    parts_read = ("metadata",)

    def __init__(self, output_folder: DataFolderLike):
        super().__init__()
        self.output_folder = output_folder

    def run(self, data, rank: int = 0, world_size: int = 1):
        from datatrove.io import get_datafolder

        from ..base.page import ERRORS_KEY
        from ..readers.resources import RESOURCE_KEY

        folder, f = get_datafolder(self.output_folder), None
        try:
            for doc in data:
                record = doc.metadata.get(RESOURCE_KEY)
                if record is not None:
                    if f is None:
                        f = folder.open(f"{rank:05d}.jsonl.gz", "wt", compression="gzip")
                    line = {**record, **({"errors": doc.metadata[ERRORS_KEY]} if doc.metadata.get(ERRORS_KEY) else {})}
                    f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
                    self.stat_update("records")
                yield doc
        finally:
            if f is not None:
                f.close()
