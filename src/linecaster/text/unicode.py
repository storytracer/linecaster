"""Unicode normalization of the as-written layer: ``normalize_transcription(t, form="NFC")``.

linecaster's text is NFC (CLAUDE.md). Recognizers do not all deliver it: kraken's PP-OCRv6 models write
``ä`` as ``a`` + U+0308 (decomposed). The ``UnicodeNormalizer`` block (``linecaster.blocks.text.unicode``) runs
this right after recognition. It is a separate step, not part of a backend, so that an engine's raw
output stays what the engine produced (and testable against the engine itself), and the step is
recorded: an ``Annotator(kind="rule", step="unicode", name="unicodedata", settings={"form", "unicode_version"})``.
Parity with a reference that did not normalize is then "byte-exact after NFC on both sides".

The readings stay as the recognizer gave them: where a line's text or a word's text is not NFC, the step adds an
``Edit(kind="nfc")`` with the NFC text, targeting the line (its id) or the word (``<line>/<n>``); where it is NFC
already, nothing. ``Transcription.text_of(line)`` reads a line's text with its edit applied. Boxes, confidences and
ids are untouched (a word's box covers the same glyphs whatever the code points); alternatives keep their code
points (a reference names no alternative). NFC is a canonical equivalence: it never changes what is written, only
how it is encoded; a compatibility form (NFKC, which would fold ligatures, long s and superscripts) is refused here,
those are the readable variants' job.
"""
from __future__ import annotations

import time
import unicodedata
from datetime import datetime, timezone

from ..data.refs import word
from ..data.transcription import Annotator, Edit, Transcription

#: the forms the step writes: NFC (its edits are ``nfc`` edits)
FORMS = ("NFC",)


def normalize_transcription(t: Transcription, form: str = "NFC") -> int:
    """Adds an ``nfc`` edit for every line and word text that is not NFC (one annotator, step ``unicode``); returns
    how many it added."""
    if form not in FORMS:
        raise ValueError(f"form {form!r}: linecaster keeps canonical equivalence only ({', '.join(FORMS)}); "
                         "compatibility folding belongs to the readable text variants")
    start, began = time.perf_counter(), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    a = t.add_annotator(Annotator(kind="rule", step="unicode", name="unicodedata",
                                  settings={"form": form, "unicode_version": unicodedata.unidata_version}))
    changed = 0

    def edit(target: str, text: str) -> None:
        nonlocal changed
        n = unicodedata.normalize(form, text)
        if n != text:
            t.edits.append(Edit(annotator=a, target=target, kind="nfc", text=n))
            changed += 1

    for ln in t.lines:
        if ln.reading is None:
            continue
        edit(ln.id, ln.reading.text)
        for k, w in enumerate(ln.reading.words):
            edit(word(ln.id, k), w.text)
    t.annotators[a].measurements.update({"changed": changed, "seconds": round(time.perf_counter() - start, 4),
                                         "datetime": began})
    return changed
