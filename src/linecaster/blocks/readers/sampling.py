"""Readers that read a sample of their input (``linecaster.data.sample``): the rule's pages, chosen from the ids of
the input's listing before any image is read or fetched.

A reader with a ``sample`` rule computes the sample once (``sampled()``) and keeps it, so it travels with the
pickled pipeline: the launch computes it (it records it and writes ``OUT/sample.parquet``), and every task takes its
share of the same sample. A reader built without the launch (a test, ``run_pages``) computes it in each task from the
whole listing, with the same result, so the sample never depends on ``--tasks``. ``--limit`` and ``--skip`` still
count per task, over the task's share.
"""
from __future__ import annotations

from ...data.sample import Sample, SampleRule
from ...errors import PipelineConfigError


class Sampled:
    """What the readers with a ``sample`` share: the rule, the kept sample, and ``sampled()``."""

    sample: SampleRule | None = None
    _sample: Sample | None = None

    def _set_sample(self, sample: SampleRule | dict | None, max_pages: int | None = None) -> None:
        if isinstance(sample, dict):
            sample = SampleRule(**sample)
        if sample is not None and not isinstance(sample, SampleRule):
            raise PipelineConfigError(f"sample is a SampleRule, not {sample!r}")
        if sample is not None and max_pages is not None:
            raise PipelineConfigError("sample and max_pages exclude each other: a sample's first N pages are "
                                      "SampleRule(pages=N)")
        self.sample, self._sample = sample, None

    def sampled(self, save: bool = True) -> Sample:
        """The sample of the input under ``sample`` (computed once and kept). ``save``: a reader whose listing
        costs requests (manifests) keeps copies of what it read; False for ``--dry-run``."""
        if self.sample is None:
            raise PipelineConfigError(f"{type(self).__name__} has no sample rule")
        if self._sample is None:
            self._sample = self._compute_sample(save)
        return self._sample

    def _compute_sample(self, save: bool) -> Sample:
        raise NotImplementedError
