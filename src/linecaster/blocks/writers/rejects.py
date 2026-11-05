"""``RejectWriter``: the pages that carry errors (``doc.metadata["errors"]``: a block failed on them, or a check
rejected them), one JSON line per error in ``<folder>/<prefix><rank:05d>.jsonl``, opened on the first reject (a
task without rejects leaves no file): ``key`` (the page id), ``field``, ``error`` and ``raw_value``, plus the
entry's ``block``, ``step``, ``preset`` and ``type``, so nothing disappears silently. Every page goes on: the page
records keep the failed pages with their errors.

The builder puts one before the first writer of a pipeline with a run folder (``<run_folder>/rejects``); only this
writer knows the task, so the blocks that reject pages only record why."""
from __future__ import annotations

import json

from datatrove.io import DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep

from ..base.contract import Contracted
from ..base.page import ERRORS_KEY

#: the keys of an error entry that become a reject's own fields
OWN = ("field", "error", "raw_value")


def reject(key: str, entry: dict) -> dict:
    """One reject line for the error ``entry`` of page ``key``: its ``field`` (else the step or block that failed),
    ``error``, ``raw_value``, and the entry's other keys."""
    field = entry.get("field") or entry.get("step") or entry.get("block")
    return {"key": key, "field": field, "error": entry.get("error"), "raw_value": entry.get("raw_value"),
            **{k: v for k, v in entry.items() if k not in OWN}}


class RejectWriter(Contracted, PipelineStep):
    """Write every page that carries errors to ``<output_folder>/<prefix><rank:05d>.jsonl`` (one line per error)
    and pass every page on. ``prefix`` keeps two writers that share a folder apart."""

    type = "💽 - WRITER"
    name = "🗑 rejects"
    role = "writer"

    def __init__(self, output_folder: DataFolderLike, prefix: str = ""):
        super().__init__()
        self.output_folder, self.prefix = output_folder, prefix

    def run(self, data, rank: int = 0, world_size: int = 1):
        folder, name, f = get_datafolder(self.output_folder), f"{self.prefix}{rank:05d}.jsonl", None
        try:
            for doc in data:
                errors = doc.metadata.get(ERRORS_KEY) or ()
                if errors:
                    if f is None:
                        f = folder.open(name, "wt")
                    for entry in errors:
                        f.write(json.dumps(reject(doc.id, entry), ensure_ascii=False, default=str) + "\n")
                    self.stat_update("rejected")
                yield doc
        finally:
            if f is not None:
                f.close()
