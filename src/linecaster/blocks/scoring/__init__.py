"""Scoring: a run's pages scored against a ground truth's, by a benchmark (``pipelines/score.py``) or by
OmniDocBench's own evaluation (``pipelines/harness.py``)."""
from .omnidocbench import OmniDocBenchScorer
from .pages import PageScorer

__all__ = ["OmniDocBenchScorer", "PageScorer"]
