"""``HarnessWriter``: a task's pages scored by a benchmark's own harness (``linecaster.scoring.harness``): the task
collects its pages, reads their ground truth in one pass, writes them as a shard (``OUT/shards/<task>``: the
harness's ground-truth file and one prediction per page) and runs the harness on it in one process. The pipeline
``harness.v1`` puts the shards' results together when every task is done (``linecaster.scoring.harness.finish``)."""
from __future__ import annotations

from datatrove.pipeline.base import PipelineStep

from ..base.contract import Contracted


class HarnessWriter(Contracted, PipelineStep):
    """Writes the task's pages as a harness shard and runs the harness on it; the pages are passed on.

    The page's transcription ``transcription`` (the page record's, ``doc.metadata["page"]``; a page with errors: an
    empty prediction) against the ground truth's page of the same id (``truth_transcription``). A page outside
    ``ids`` (when given) is passed by (stat ``outside``); a page without ground truth too (stat ``no_truth``).

    Args:
        output_folder: the harness's run folder (``OUT``; the task's shard goes to ``OUT/shards/<task>``).
        truth: the ground truth's page records (a folder: local path or fsspec URI).
        harness: the harness (``linecaster.scoring.harness.HARNESSES``).
        transcription: the run's transcription scored.
        truth_transcription: the ground truth's transcription.
        ids: only these pages (the benchmark's page set), or every page of the run.
        cdm: OmniDocBench's CDM for formulas too.
    """

    type = "🔠 - LINECASTER"
    name = "🧪 harness writer"
    docs_args = {"output_folder": "OUT", "truth": "truth/pages", "harness": "omnidocbench"}

    def __init__(self, output_folder: str, truth: str, harness: str = "omnidocbench", transcription: str = "ocr_new",
                 truth_transcription: str = "ground_truth", ids: list[str] | None = None, cdm: bool = False):
        super().__init__()
        self.output_folder, self.truth, self.harness = output_folder, truth, harness
        self.transcription, self.truth_transcription = transcription, truth_transcription
        self.ids, self.cdm = (set(ids) if ids is not None else None), cdm

    def run(self, data, rank: int = 0, world_size: int = 1):
        import shutil
        from pathlib import Path

        from ...scoring.harness import run_shard, write_shard
        from ...scoring.run import read_truth

        docs = [d for d in data]
        rows = {}
        for d in docs:
            if self.ids is not None and d.id not in self.ids:
                self.stat_update("outside")
                continue
            rows[d.id] = {"id": d.id, "page": d.metadata.get("page"), "errors": d.metadata.get("errors")}
        if not rows:
            yield from docs
            return
        with self.track_time("truth"):
            truths = read_truth(self.truth, set(rows))
        for pid in [p for p in rows if p not in truths]:
            self.stat_update("no_truth")
            del rows[pid]
        folder = Path(self.output_folder) / "shards" / f"{rank:05d}"
        shutil.rmtree(folder, ignore_errors=True)
        with self.track_time("export"):
            counts = write_shard(folder, {p: truths[p] for p in rows}, rows, self.transcription,
                                 self.truth_transcription)
        with self.track_time("harness"):
            run_shard(self.harness, folder, self.cdm, workers=1)
        self.stat_update("pages", value=counts["pages"])
        yield from docs
