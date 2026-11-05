"""Unicode normalization of the as-written layer: ``normalize_transcription(t, form="NFC")``.

linecaster's text is NFC (CLAUDE.md). Recognizers do not all deliver it: kraken's PP-OCRv6 models write
``ä`` as ``a`` + U+0308 (decomposed). The ``UnicodeNormalizer`` block (``linecaster.blocks.text.unicode``) runs
this right after recognition. It is a separate step, not part of a backend, so that an engine's raw
output stays what the engine produced (and testable against the engine itself), and the step is
recorded: ``StepInfo(step="unicode", name="unicodedata", settings={"form", "unicode_version"})``.
Parity with a reference that did not normalize is then "byte-exact after NFC on both sides".

Normalized: ``Line.text``, ``Line.alternatives``, ``Word.text``, ``Word.alternatives``. Boxes,
confidences and ids are unchanged (a word's box covers the same glyphs whatever the code points).
NFC is a canonical equivalence: it never changes what is written, only how it is encoded; NFKC (which
would fold ligatures, long s and superscripts) is refused here, those are the readable variants' job.
"""
from __future__ import annotations

import unicodedata

from ..data.transcription import StepInfo, Transcription

FORMS = ("NFC", "NFD")


def normalize_transcription(t: Transcription, form: str = "NFC") -> int:
    """Normalize the transcription's line and word texts in place; returns how many strings changed."""
    if form not in FORMS:
        raise ValueError(f"form {form!r}: linecaster keeps canonical equivalence only ({', '.join(FORMS)}); "
                         "compatibility folding belongs to the readable text variants")
    changed = 0

    def norm(s):
        nonlocal changed
        if s is None:
            return s
        n = unicodedata.normalize(form, s)
        changed += n != s
        return n

    for ln in t.lines:
        ln.text = norm(ln.text)
        ln.alternatives = [norm(a) for a in ln.alternatives]
        for w in ln.words:
            w.text = norm(w.text)
            w.alternatives = [norm(a) for a in w.alternatives]
    t.steps.append(StepInfo(step="unicode", name="unicodedata",
                            settings={"form": form, "unicode_version": unicodedata.unidata_version},
                            measurements={"changed": changed}))
    return changed
