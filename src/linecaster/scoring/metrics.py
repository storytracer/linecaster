"""Per-page metrics of an output against a ground truth: edit counts per text and lane, word recall and
over-extraction, the words per content role, and the role confusion of regions matched by their boxes."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ..data.policy import DEFAULT_POLICY, RenderingPolicy
from ..data.transcription import Transcription
from .counts import edit_counts
from .lanes import DEFAULT_LANE, REPLACEMENT, normalize
from .render import TEXTS, text

_PUNCT = re.compile(rf"[^\w\s{REPLACEMENT}]")


def words(s: str, lane: str = DEFAULT_LANE) -> Counter:
    """The words of a text for recall and role agreement: whitespace tokens of the lane (the one scored), punctuation
    dropped; a word with an illegible character is left out (no output can be required to have it)."""
    return Counter(w for w in _PUNCT.sub(" ", normalize(s, lane)).split() if REPLACEMENT not in w)


def _overlap(a: Counter, b: Counter) -> int:
    return sum((a & b).values())


def role_words(t: Transcription, policy: RenderingPolicy = DEFAULT_POLICY, lane: str = DEFAULT_LANE
               ) -> dict[str, Counter]:
    """Content role -> the words (by ``lane``) of the lines in regions of that role (lines in no region:
    ``paragraph``)."""
    prec = policy.precedence.get("role")
    out: dict[str, Counter] = {}
    for ln in t.ordered_lines():
        s = t.text_of(ln)
        if not s:
            continue
        region = t.region_of(ln)
        role = (t.classification(region, "role", prec) if region else None) or "paragraph"
        out.setdefault(role, Counter()).update(words(s, lane))
    return out


def iou(a, b) -> float:
    ax0, ay0, ax1, ay1 = a[0], a[1], a[0] + a[2], a[1] + a[3]
    bx0, by0, bx1, by1 = b[0], b[1], b[0] + b[2], b[1] + b[3]
    w, h = min(ax1, bx1) - max(ax0, bx0), min(ay1, by1) - max(ay0, by0)
    inter = max(w, 0) * max(h, 0)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def confusion(truth: Transcription, output: Transcription, threshold: float = 0.5,
              policy: RenderingPolicy = DEFAULT_POLICY) -> list[dict[str, Any]]:
    """The role confusion of regions matched one to one by IoU (greedy, highest first, at least ``threshold``);
    unmatched regions on either side against ``none``. Only regions with boxes take part."""
    prec = policy.precedence.get("role")
    ts = [r for r in truth.regions if r.box is not None]
    os_ = [r for r in output.regions if r.box is not None]
    pairs = sorted(((iou(a.box, b.box), i, j) for i, a in enumerate(ts) for j, b in enumerate(os_)), reverse=True)
    used_t, used_o, counts = set(), set(), Counter()
    for score, i, j in pairs:
        if score < threshold:
            break
        if i in used_t or j in used_o:
            continue
        used_t.add(i), used_o.add(j)
        counts[(truth.role(ts[i].id, prec) or "paragraph", output.role(os_[j].id, prec) or "paragraph")] += 1
    for i, r in enumerate(ts):
        if i not in used_t:
            counts[(truth.role(r.id, prec) or "paragraph", "none")] += 1
    for j, r in enumerate(os_):
        if j not in used_o:
            counts[("none", output.role(r.id, prec) or "paragraph")] += 1
    return [{"role_true": a, "role_output": b, "count": n} for (a, b), n in sorted(counts.items())]


def score_page(truth: Transcription, output: Transcription | None, texts=tuple(TEXTS), lanes=(DEFAULT_LANE,),
               policy: RenderingPolicy = DEFAULT_POLICY, boxes: bool = True, unit: str = "grapheme",
               strategy: str = "literal") -> dict[str, Any]:
    """One page's counts: ``rows`` (one per text and lane: ``s``, ``d``, ``i``, ``h``, ``n`` in ``unit``s, the
    word counts ``words_true``, ``words_output``, ``words_both`` by that lane, and ``conventions``: the
    normalizations the ground truth declares (``Source.normalized``) that the lane and the output strategy do not
    apply, ``linecaster.scoring.lanes.uncovered``), ``roles`` (role -> true, output, both
    word counts, by the first lane) and, with ``boxes``, ``confusion``. Both texts are written by the output
    ``strategy`` (``literal``: as read) before a lane normalizes them. A missing output (a failed page) counts as
    empty."""
    from .lanes import lane as lane_of, uncovered
    from ..catalog.registry import catalog

    output = output if output is not None else Transcription()
    written = catalog().strategy(strategy, use="output")
    rows = []
    for name in texts:
        ref, hyp = written.text(text(truth, name, policy)), written.text(text(output, name, policy))
        for ln in lanes:
            ln = lane_of(ln)
            wt, wo = words(ref, ln), words(hyp, ln)
            c = edit_counts(normalize(ref, ln), normalize(hyp, ln), unit)
            rows.append({"text": name, "lane": ln, "unit": unit, "s": c.s, "d": c.d, "i": c.i, "h": c.h, "n": c.n,
                         "words_true": sum(wt.values()), "words_output": sum(wo.values()),
                         "words_both": _overlap(wt, wo),
                         "conventions": uncovered(truth.source.normalized, ln, strategy)})
    first = lane_of(lanes[0]) if lanes else DEFAULT_LANE
    rt, ro = role_words(truth, policy, first), role_words(output, policy, first)
    roles = {role: {"true": sum(rt.get(role, Counter()).values()), "output": sum(ro.get(role, Counter()).values()),
                    "both": _overlap(rt.get(role, Counter()), ro.get(role, Counter()))}
             for role in sorted(set(rt) | set(ro))}
    out = {"rows": rows, "roles": roles}
    if boxes:
        out["confusion"] = confusion(truth, output, policy=policy)
    return out
