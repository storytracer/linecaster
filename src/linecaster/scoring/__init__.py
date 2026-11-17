"""Scoring transcriptions against ground truths: the texts a benchmark scores, rendered under a rendering policy
(``render``), normalized by lanes (comparison strategies of the catalog, ``lanes``), counted per page by grapheme
cluster or code point (``counts``, ``metrics``) and aggregated into corpus rates with bootstrap intervals over items
(``aggregate``). A score names the linecaster that made it (``scorer``). Import-light, like ``linecaster.data``: the
alignment needs ``rapidfuzz`` (the extra ``linecaster[rapidfuzz]``), imported when counting."""
from linecaster.scoring.aggregate import RATES, rates, role_rates
from linecaster.scoring.counts import UNITS, EditCounts, edit_counts
from linecaster.scoring.elements import ELEMENTS_VERSION
from linecaster.scoring.lanes import DEFAULT_LANE, LEGACY, REPLACEMENT, lane, normalize
from linecaster.scoring.metrics import confusion, role_words, score_page, words
from linecaster.scoring.render import TEXTS, text
from linecaster.scoring.tokens import WORDS, WORDS_VERSION, tokens


def scorer() -> str:
    """What scored: the linecaster release and commit (``linecaster.data.transcription.producer``), in every score
    and evidence record (before 0.10, ``linecaster-scorer@1``)."""
    from linecaster.data.transcription import producer

    return f"linecaster {producer()}"


__all__ = ["DEFAULT_LANE", "ELEMENTS_VERSION", "LEGACY", "RATES", "REPLACEMENT", "TEXTS", "UNITS", "EditCounts", "confusion",
           "edit_counts", "lane", "normalize", "rates", "role_rates", "role_words", "score_page", "scorer", "text",
           "tokens", "WORDS", "WORDS_VERSION", "words"]
