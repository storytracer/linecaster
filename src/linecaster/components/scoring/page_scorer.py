"""``PageScorer``: each page of a run scored against its ground truth, by a benchmark: the page's score records and
its summary on the document (``doc.metadata["score"]``), for ``ScoreWriter``.

A task collects its pages first (their ids), reads their ground truth from the truth folder in one pass
(``linecaster.evaluation.run.read_truth``: only those lines decoded), then scores each (``score_pair``). A page outside
the benchmark's page set is passed by unscored (stat ``outside``); a page of the set without ground truth is an
error. The pages a run lacks are scored as empty outputs when the tasks' scores are put together
(``linecaster.evaluation.run.aggregate``)."""
from __future__ import annotations

from typing import Any

from datatrove.pipeline.base import PipelineStep

from linecaster.core.contract import Contracted

SCORE_KEY = "score"


class PageScorer(Contracted, PipelineStep):
    """Scores each page of the stream against its ground truth, by a benchmark.

    The page's transcription ``transcription`` (the page record's, ``doc.metadata["page"]``; a page with errors
    scores as an empty output) is compared with the ground truth's page of the same id, rendered and normalized as
    the benchmark says (``linecaster.evaluation.run.score_pair``): ``doc.metadata["score"]`` gets ``records`` (one per
    text and lane) and ``page`` (the page's summary: roles, confusion, missing, failed).

    Args:
        truth: the ground truth's page records (a folder: local path or fsspec URI).
        benchmark: the benchmark definition (its YAML's content: ``linecaster.benchmark/2``).
        transcription: the run's transcription scored.
        run_id: the scored run's id, on every score record.
    """

    type = "🔠 - LINECASTER"
    name = "🎯 page scorer"
    docs_args = {"truth": "truth/pages", "benchmark": {}}

    def __init__(self, truth: str, benchmark: dict[str, Any], transcription: str = "ocr_new",
                 run_id: str | None = None):
        super().__init__()
        self.truth, self.benchmark, self.transcription, self.run_id = truth, benchmark, transcription, run_id

    def run(self, data, rank: int = 0, world_size: int = 1):
        from linecaster.catalog.registry import rendering_policy
        from linecaster.evaluation.benchmark import read_benchmark
        from linecaster.evaluation.run import read_truth, score_pair, wanted_pages

        bench = read_benchmark(self.benchmark)
        policy = rendering_policy(bench.policy)
        want = set(wanted_pages(bench)) if bench.pages.ids is not None else None
        docs = list(data)                       # the task's pages first: their ids say which truth lines to read
        ids = {d.id for d in docs if want is None or d.id in want}
        with self.track_time("truth"):
            truths = read_truth(self.truth, ids)
        for doc in docs:
            if doc.id not in ids:
                self.stat_update("outside")
                yield doc
                continue
            if doc.id not in truths:
                raise ValueError(f"page {doc.id} of the page set is not in the ground truth {self.truth}")
            row = {"id": doc.id, "page": doc.metadata.get("page"), "errors": doc.metadata.get("errors")}
            with self.track_time():
                records, summary = score_pair(doc.id, truths[doc.id], row, bench, self.transcription, policy,
                                              self.run_id)
            doc.metadata[SCORE_KEY] = {"records": records, "page": summary}
            self.stat_update("pages")
            if summary["failed"]:
                self.stat_update("failed")
            yield doc
