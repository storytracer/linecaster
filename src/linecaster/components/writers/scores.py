"""``ScoreWriter``: the score records ``PageScorer`` put on each page, one gzipped JSON Lines file per task:
``<folder>/records/<rank:05d>.jsonl.gz`` (one line per text and lane of each page) and
``<folder>/pages/<rank:05d>.jsonl.gz`` (one line per page: its summary), which
``linecaster.scoring.run.aggregate`` puts together. A rerun of a task writes its files again."""
from __future__ import annotations

import json

from datatrove.io import DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep

from linecaster.core.contract import Contracted
from linecaster.components.scoring.page_scorer import SCORE_KEY


class ScoreWriter(Contracted, PipelineStep):
    """Writes each page's score records and summary (``doc.metadata["score"]``) and passes the page on.

    Args:
        output_folder: the scores folder (local path or fsspec URI): ``records/`` and ``pages/`` in it.
    """

    type = "💽 - WRITER"
    name = "🎯 score records"
    role = "writer"
    docs_args = {"output_folder": "out/scores"}

    def __init__(self, output_folder: DataFolderLike):
        super().__init__()
        self.output_folder = output_folder

    def run(self, data, rank: int = 0, world_size: int = 1):
        folder = get_datafolder(self.output_folder)
        name = f"{rank:05d}.jsonl.gz"
        with folder.open(f"records/{name}", "wt", compression="gzip", encoding="utf-8") as rec, \
                folder.open(f"pages/{name}", "wt", compression="gzip", encoding="utf-8") as pages:
            for doc in data:
                score = doc.metadata.get(SCORE_KEY)
                if score is not None:
                    for r in score["records"]:
                        rec.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
                    pages.write(json.dumps(score["page"], ensure_ascii=False, default=str) + "\n")
                    self.stat_update("pages")
                yield doc
