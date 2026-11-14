"""Scoring transcriptions against ground truths: the texts a benchmark scores, rendered under a rendering policy
(``render``), normalized by versioned lanes (``lanes``), counted per page (``counts``, ``metrics``) and aggregated
into corpus rates with bootstrap intervals over items (``aggregate``). Import-light, like ``linecaster.data``: the
alignment needs ``rapidfuzz`` (the extra ``linecaster[rapidfuzz]``), imported when counting."""
from .aggregate import RATES, rates, role_rates
from .counts import EditCounts, edit_counts
from .lanes import DEFAULT_LANE, LANES, REPLACEMENT, lane, normalize
from .metrics import confusion, role_words, score_page, words
from .render import TEXTS, text

#: the scorer's edition, in every score record and evidence record
SCORER = "linecaster-scorer@1"

__all__ = ["DEFAULT_LANE", "LANES", "RATES", "REPLACEMENT", "SCORER", "TEXTS", "EditCounts", "confusion", "edit_counts", "lane",
           "normalize", "rates", "role_rates", "role_words", "score_page", "text", "words"]
