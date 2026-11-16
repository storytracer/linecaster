"""Omni Parse Bench's prediction format (datalab-to/omni_parse_bench, the package ``omni-parse-bench``, the extra
``omniparsebench``): a run's page as the file Omni Parse Bench grades, ``predictions/<page_id>.json``::

    {"pages": [{"html": "..."}]}

The page is written as Markdown (``linecaster.formats.omnidocbench.prediction_markdown``: the model's blocks in its
reading order, its text as it read it, tables as HTML, formulas as ``$$..$$``; a completion without regions as its
lines), then through Omni Parse Bench's own Markdown converter (``omni_parse_bench.markdown.to_html``), the one every
provider's Markdown goes through there. Nothing is normalized: the scorer's own fold does that, on every system alike.

Only the ``html`` output is written: tests that read ``blocks`` (``layout_kind``) need the blocks' places, which a
dataset without them never asks for. The tests are the dataset's own; linecaster writes predictions, Omni Parse Bench
grades them (``pipelines/omniparsebench.py``).
"""
from __future__ import annotations

from ..data.policy import DEFAULT_POLICY, RenderingPolicy
from ..data.transcription import Transcription


def page_html(t: Transcription | None, policy: RenderingPolicy = DEFAULT_POLICY) -> str:
    """A run's page ``t`` as the HTML Omni Parse Bench grades; an empty string for a page without a transcription."""
    from omni_parse_bench import markdown

    from .omnidocbench import prediction_markdown

    return markdown.to_html(prediction_markdown(t, policy))


def prediction(t: Transcription | None, policy: RenderingPolicy = DEFAULT_POLICY) -> dict:
    """A run's page as the content of its prediction file (module docstring)."""
    return {"pages": [{"html": page_html(t, policy)}]}
