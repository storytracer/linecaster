"""``OmniDocBenchScorer``: each page of a run scored by OmniDocBench's own evaluation, in this process
(``linecaster.scoring.omnidocbench``): the task collects its pages, reads their ground truth in one pass, writes both
sides in OmniDocBench's formats in memory and runs the harness's matching and metrics on them. Each page gets its
samples (``doc.metadata["omnidocbench"]``) for ``OmniDocBenchWriter``; the pipeline ``harness.v1`` puts every task's
samples together by the harness's own aggregation when the tasks are done."""
from __future__ import annotations

from datatrove.pipeline.base import PipelineStep

from ..base.contract import Contracted

OMNIDOCBENCH_KEY = "omnidocbench"


class OmniDocBenchScorer(Contracted, PipelineStep):
    """Scores the task's pages by OmniDocBench's evaluation; ``doc.metadata["omnidocbench"]`` gets the page
    (``page_summary``: name, attributes, categories) and its samples per module, each with its metrics.

    The page's transcription ``transcription`` (a page with errors: an empty prediction) against the ground truth's
    page of the same id. A page outside ``ids`` (when given) is passed by (stat ``outside``); a page without ground
    truth too (stat ``no_truth``).

    Args:
        truth: the ground truth's page records (a folder: local path or fsspec URI).
        transcription: the run's transcription scored.
        truth_transcription: the ground truth's transcription.
        ids: only these pages (the benchmark's page set), or every page of the run.
    """

    type = "🔠 - LINECASTER"
    name = "🧪 OmniDocBench scorer"
    docs_args = {"truth": "truth/pages"}

    def __init__(self, truth: str, transcription: str = "ocr_new", truth_transcription: str = "ground_truth",
                 ids: list[str] | None = None):
        super().__init__()
        self.truth, self.transcription, self.truth_transcription = truth, transcription, truth_transcription
        self.ids = set(ids) if ids is not None else None

    def run(self, data, rank: int = 0, world_size: int = 1):
        from ...data import Page
        from ...data.upgrade import upgrade
        from ...formats.omnidocbench import prediction_markdown, truth_page
        from ...scoring.harness import _attributes
        from ...scoring.omnidocbench import page_key, page_summary, score_pages
        from ...scoring.run import read_truth

        docs = list(data)
        want = [d for d in docs if self.ids is None or d.id in self.ids]
        self.stat_update("outside", value=len(docs) - len(want))
        if not want:
            yield from docs
            return
        with self.track_time("truth"):
            truths = read_truth(self.truth, {d.id for d in want})
        pages, summaries = [], {}
        with self.track_time("export"):
            for d in want:
                if d.id not in truths:
                    self.stat_update("no_truth")
                    continue
                gt = Page.model_validate(upgrade(truths[d.id])["page"]).transcriptions[self.truth_transcription]
                gt_page = truth_page(d.id, gt, attributes=_attributes(gt))
                t = None
                if not d.metadata.get("errors") and d.metadata.get("page"):
                    t = Page.model_validate(d.metadata["page"]).transcriptions.get(self.transcription)
                pages.append((gt_page, prediction_markdown(t)))
                summaries[d.id] = page_summary(gt_page)
        with self.track_time("harness"):
            samples = score_pages(pages)
        by_page: dict[str, dict[str, list]] = {}
        for element, ss in samples.items():
            for s in ss:
                by_page.setdefault(page_key(s).removesuffix(".png"), {}).setdefault(element, []).append(s)
        for d in docs:
            if d.id in summaries:
                d.metadata[OMNIDOCBENCH_KEY] = {"page": summaries[d.id], "samples": by_page.get(d.id, {})}
                self.stat_update("pages")
        yield from docs
