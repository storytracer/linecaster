"""``OmniDocBenchWriter``: the OmniDocBench samples ``OmniDocBenchScorer`` put on each page, one gzipped JSON Lines file
per task: ``<folder>/samples/<rank:05d>.jsonl.gz`` (one line per page: its summary and samples), which the pipeline
``harness.v1`` puts together (``linecaster.scoring.omnidocbench.aggregate``). A rerun of a task writes its file
again."""
from __future__ import annotations

import json

from datatrove.io import DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep

from ..base.contract import Contracted
from ..scoring.omnidocbench import OMNIDOCBENCH_KEY


class OmniDocBenchWriter(Contracted, PipelineStep):
    """Writes each page's OmniDocBench samples (``doc.metadata["omnidocbench"]``) and passes the page on.

    Args:
        output_folder: the harness's run folder (local path or fsspec URI): ``samples/`` in it.
    """

    type = "💽 - WRITER"
    name = "🧪 OmniDocBench samples"
    role = "writer"
    docs_args = {"output_folder": "out/omnidocbench"}

    def __init__(self, output_folder: DataFolderLike):
        super().__init__()
        self.output_folder = output_folder

    def run(self, data, rank: int = 0, world_size: int = 1):
        folder = get_datafolder(self.output_folder)
        with folder.open(f"samples/{rank:05d}.jsonl.gz", "wt", compression="gzip", encoding="utf-8") as fh:
            for doc in data:
                got = doc.metadata.get(OMNIDOCBENCH_KEY)
                if got is not None:
                    fh.write(json.dumps({"id": doc.id, **got}, ensure_ascii=False, default=str) + "\n")
                    self.stat_update("pages")
                yield doc
