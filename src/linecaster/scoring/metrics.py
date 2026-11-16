"""Per-page metrics of an output against a ground truth: edit counts per text and lane, word recall and
over-extraction, the words per content role, and the role confusion of regions matched by their boxes."""
from __future__ import annotations

from collections import Counter
from typing import Any

from ..data.policy import DEFAULT_POLICY, RenderingPolicy
from ..data.transcription import Transcription
from .counts import edit_counts
from .lanes import DEFAULT_LANE, REPLACEMENT, normalize
from .render import TEXTS, illegible_spans, line_text, text
from .tokens import DEFAULT_WORDS, tokens


def words(s: str, lane: str = DEFAULT_LANE, tokenizer: str = DEFAULT_WORDS) -> Counter:
    """The words of a text for recall and role agreement: the ``tokenizer``'s tokens (``linecaster.scoring.tokens``)
    of the lane's text (the one scored); a word with an illegible character is left out (no output can be required to
    have it)."""
    return Counter(w for w in tokens(normalize(s, lane), tokenizer) if REPLACEMENT not in w)


def _overlap(a: Counter, b: Counter) -> int:
    return sum((a & b).values())


def role_words(t: Transcription, policy: RenderingPolicy = DEFAULT_POLICY, lane: str = DEFAULT_LANE,
               strategy="literal", tokenizer: str = DEFAULT_WORDS) -> dict[str, Counter]:
    """Content role -> the words (by ``lane`` and ``tokenizer``) of the lines in regions of that role (lines in no
    region: ``paragraph``), each line written as the scored texts are: its illegible spans as U+FFFD, then the output
    ``strategy`` (a reference, or the strategy resolved)."""
    from ..catalog.registry import catalog

    written = catalog().strategy(strategy, use="output") if isinstance(strategy, str) else strategy
    prec = policy.precedence.get("role")
    illegible = illegible_spans(t)
    out: dict[str, Counter] = {}
    for ln in t.ordered_lines():
        s = line_text(t, ln, illegible)
        if not s:
            continue
        region = t.region_of(ln)
        role = (t.classification(region, "role", prec) if region else None) or "paragraph"
        out.setdefault(role, Counter()).update(words(written.text(s), lane, tokenizer))
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
               strategy: str = "literal", tokenizer: str = DEFAULT_WORDS) -> dict[str, Any]:
    """One page's counts: ``rows`` (one per text and lane: ``s``, ``d``, ``i``, ``h``, ``n`` in ``unit``s, the
    word counts ``words_true``, ``words_output``, ``words_both`` by that lane and the ``tokenizer``
    (``linecaster.scoring.tokens``), and ``conventions``: the
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
            wt, wo = words(ref, ln, tokenizer), words(hyp, ln, tokenizer)
            c = edit_counts(normalize(ref, ln), normalize(hyp, ln), unit)
            rows.append({"text": name, "lane": ln, "unit": unit, "words": tokenizer, "s": c.s, "d": c.d, "i": c.i, "h": c.h, "n": c.n,
                         "words_true": sum(wt.values()), "words_output": sum(wo.values()),
                         "words_both": _overlap(wt, wo),
                         "conventions": uncovered(truth.source.normalized, ln, strategy)})
    first = lane_of(lanes[0]) if lanes else DEFAULT_LANE
    rt = role_words(truth, policy, first, written, tokenizer)
    ro = role_words(output, policy, first, written, tokenizer)
    roles = {role: {"true": sum(rt.get(role, Counter()).values()), "output": sum(ro.get(role, Counter()).values()),
                    "both": _overlap(rt.get(role, Counter()), ro.get(role, Counter()))}
             for role in sorted(set(rt) | set(ro))}
    out = {"rows": rows, "roles": roles}
    if boxes:
        out["confusion"] = confusion(truth, output, policy=policy)
    return out


#: the fields every element row has (``score_elements``), so that a table of them has one schema
ELEMENT_FIELDS = ("level", "text", "lane", "unit", "side", "element", "index", "kind", "role", "layer", "group",
                  "match", "s", "d", "i", "h", "n", "m", "teds", "teds_s", "table_kind", "as_table", "latex_s",
                  "latex_d", "latex_i", "latex_h", "latex_n", "latex_m", "attributes")


def _element_row(**fields) -> dict[str, Any]:
    row = dict.fromkeys(ELEMENT_FIELDS)
    row.update(level="element", **fields)
    return row


def score_elements(truth: Transcription, output: Transcription | None, texts=tuple(TEXTS), lanes=(DEFAULT_LANE,),
                   policy: RenderingPolicy = DEFAULT_POLICY, unit: str = "grapheme", strategy: str = "literal",
                   settings=None, tables: str = "data", matching_lane: str | None = None) -> dict[str, Any]:
    """One page compared element by element (``linecaster.scoring.elements``, ``linecaster.scoring.matching``):
    ``rows``, one per element, text and lane: a ground-truth element (``side`` ``truth``) with the edit counts its
    group's comparison gives it (``edit_counts_by``; a missed element all deletions), an output element no
    ground-truth element of that text matches (``side`` ``output``) all insertions; a table's ``teds``/``teds_s``
    against the output table of its group (0 without one) and ``as_table``; a formula's LaTeX counts (``latex_*``,
    the cleaned LaTeX without spaces, ``linecaster.text.formulas.clean``); ``m`` = max(n, h + s + i), for normalized
    edit distance. And ``page``: the reading order's counts (``order_discordant``, ``order_pairs``, ``order_edits``,
    ``order_len``, ``linecaster.scoring.order``), the groups' kinds, ``tables_output`` and ``tables_output_matched``.
    Both sides are written by the output ``strategy``, then each lane; elements are matched once, by
    ``matching_lane`` (default the first lane)."""
    from ..catalog.registry import catalog
    from ..text.formulas import clean
    from .counts import edit_counts_by, units
    from .elements import elements
    from .lanes import lane as lane_of
    from .matching import Settings, encode, match, similarity
    from .order import index_edits, kendall
    from .teds import teds

    settings = settings or Settings()
    written = catalog().strategy(strategy, use="output")
    te, oe = elements(truth, policy, tables), elements(output, policy, tables)
    lanes = [lane_of(x) for x in lanes] or [DEFAULT_LANE]
    ml = lane_of(matching_lane) if matching_lane else lanes[0]

    def prepared(e, ln):
        return normalize(written.text(e.content), ln)

    a, b = encode([units(prepared(e, ml), unit) for e in te], [units(prepared(e, ml), unit) for e in oe])
    groups = match(a, b, settings)
    rows: list[dict[str, Any]] = []

    def ident(e):
        return e.region or (e.lines[0] if e.lines else f"#{e.index}")

    def attrs(e):
        return [[s, v] for s, v in e.attributes]

    def latex_counts(g_el, o_el):
        ref = "".join(clean(g_el.latex or g_el.content).split())
        hyp = "".join(clean(o_el.latex or o_el.content).split()) if o_el is not None else ""
        c = edit_counts(ref, hyp, unit)
        return {"latex_s": c.s, "latex_d": c.d, "latex_i": c.i, "latex_h": c.h, "latex_n": c.n,
                "latex_m": max(c.n, c.h + c.s + c.i)}

    # tables and formulas paired within their groups, once (by the matching lane's similarity)
    table_pair: dict[int, int | None] = {}
    formula_pair: dict[int, int | None] = {}
    for kind, pairing in (("table", table_pair), ("formula", formula_pair)):
        for grp in groups:
            gs = [g for g in grp.truth if te[g].kind == kind]
            os_ = [o for o in grp.output if oe[o].kind == kind]
            free = list(os_)
            for g in gs:
                best = max(free, key=lambda o: (similarity(a[g], b[o]), -o), default=None)
                pairing[g] = best
                if best is not None:
                    free.remove(best)
    tables_output = sum(1 for e in oe if e.kind == "table")
    tables_output_matched = sum(1 for o in table_pair.values() if o is not None)

    for name in texts:
        layers = TEXTS[name]
        for ln in lanes:
            for k, grp in enumerate(groups):
                gs = [g for g in grp.truth if te[g].layer in layers]
                os_ = [o for o in grp.output if oe[o].layer in layers]
                common = dict(text=name, lane=ln, unit=unit, group=k, match=grp.kind)
                if gs:
                    hyp = " ".join(prepared(oe[o], ln) for o in os_)
                    counts = edit_counts_by([prepared(te[g], ln) for g in gs], hyp, unit)
                    for g, c in zip(gs, counts):
                        e = te[g]
                        extra: dict[str, Any] = {}
                        if e.kind == "table":
                            o = table_pair.get(g)
                            if o is not None:
                                text_of = (lambda s, ln=ln: normalize(written.text(s), ln))
                                extra = {"teds": teds(e.table, oe[o].table, text_of, unit),
                                         "teds_s": teds(e.table, oe[o].table, structure_only=True),
                                         "as_table": True}
                            else:
                                extra = {"teds": 0.0, "teds_s": 0.0, "as_table": False}
                        elif e.kind == "formula":
                            o = formula_pair.get(g)
                            extra = latex_counts(e, oe[o] if o is not None else None)
                        rows.append(_element_row(**common, side="truth", element=ident(e), index=e.index, kind=e.kind,
                                                 role=e.role, layer=e.layer, s=c.s, d=c.d, i=c.i, h=c.h, n=c.n,
                                                 m=max(c.n, c.h + c.s + c.i), table_kind=e.table_kind,
                                                 attributes=attrs(e), **extra))
                else:
                    for o in os_:
                        e = oe[o]
                        n_units = len(units(prepared(e, ln), unit))
                        if n_units == 0:
                            continue
                        rows.append(_element_row(**common, side="output", element=ident(e), index=e.index,
                                                 kind=e.kind, role=e.role, layer=e.layer, s=0, d=0, i=n_units, h=0,
                                                 n=0, m=n_units, table_kind=e.table_kind, attributes=attrs(e)))

    positions = {}
    for grp in groups:
        if grp.truth and grp.output:
            for g in grp.truth:
                positions[g] = min(grp.output)
    order = [positions[g] for g in sorted(positions)]
    discordant, pairs = kendall(order)
    edits, length = index_edits(order)
    kinds = Counter(grp.kind for grp in groups)
    page = {"order_discordant": discordant, "order_pairs": pairs, "order_edits": edits, "order_len": length,
            "groups": len(groups), **{f"groups_{k}": kinds.get(k, 0) for k in
                                      ("one", "split", "merge", "many", "missed", "extra", "page")},
            "elements_truth": len(te), "elements_output": len(oe), "tables_output": tables_output,
            "tables_output_matched": tables_output_matched}
    return {"rows": rows, "page": page}
