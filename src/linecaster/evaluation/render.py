"""The texts a benchmark scores, rendered from an annotation set under a rendering policy: ``full`` (the layers
``body`` and ``furniture``: everything printed on the page) and ``body`` (the body alone), as laid out (the read
lines in reading order, one per line; a region with a table as its table). What an annotator wrote about a figure
(descriptions) is in the layer the policy puts it in (``RenderingPolicy.described``; ``metadata``, in neither, by
default), after its region's text. A ground truth's illegible spans (``status`` ``illegible`` on a span of a line)
become U+FFFD, one per character; its corrections are not applied."""
from __future__ import annotations

from linecaster.data.policy import DEFAULT_POLICY, RenderingPolicy
from linecaster.data.refs import parse
from linecaster.data.transcription import Transcription, render_table
from linecaster.evaluation.lanes import REPLACEMENT

#: text name -> the layers it holds
TEXTS = {"full": ("body", "furniture"), "body": ("body",)}


def illegible_spans(t: Transcription) -> dict[str, list[tuple[int, int]]]:
    """Line id -> its illegible spans (``status`` ``illegible`` on a span of the line)."""
    out: dict[str, list[tuple[int, int]]] = {}
    for c in t.classifications:
        if c.scheme == "status" and c.value == "illegible":
            ref = parse(c.target)
            if ref.page is None and ref.span is not None and ref.word is None:
                out.setdefault(ref.id, []).append(ref.span)
    return out


def text(t: Transcription, layers: tuple[str, ...] | str, policy: RenderingPolicy = DEFAULT_POLICY) -> str:
    """The text of ``t``'s regions in ``layers`` (a ``TEXTS`` name or the layers themselves), as laid out. A region
    with a table is its table, one with a formula (a ``Formula`` of the region) ``$LaTeX$``, as a ground truth writes a
    formula, in place of its lines; such a region without lines (a layout's formula read by a formula model) takes
    its place in the regions' reading order, before the first line of a later region. A description in ``layers``
    follows its region (a picture without lines in the picture's place), one per line; the page's come last."""
    layers = TEXTS[layers] if isinstance(layers, str) else layers
    illegible = illegible_spans(t)
    layer = {r.id: policy.layer_of(t, r.id) for r in t.regions}
    tables = {tb.target: tb for tb in t.tables if tb.cells}
    formulas = {f.target: f for f in t.formulas if f.target in layer and f.latex.strip()}
    rank = t.region_ranks()
    with_lines = {t.region_of(ln) for ln in t.lines}
    described = {region: [s for lr, s in ds if lr in layers] for region, ds in policy.described(t).items()}
    described = {region: ds for region, ds in described.items() if ds}
    pending = [r.id for r in sorted(t.regions, key=lambda r: rank.get(r.id, len(rank)))
               if (r.id in tables or r.id in formulas or r.id in described) and r.id not in with_lines]
    ordered = t.ordered_lines()
    last = {region: ln.id for ln in ordered if (region := t.region_of(ln)) is not None}
    out, done = [], set()

    def whole(region: str) -> str:
        return render_table(tables[region]) if region in tables else f"${formulas[region].latex.strip()}$"

    def before(r: int) -> None:
        while pending and rank.get(pending[0], len(rank)) < r:
            region = pending.pop(0)
            if (region in tables or region in formulas) and layer.get(region, policy.layer(None)) in layers:
                out.append(whole(region))
            out.extend(described.pop(region, ()))

    for ln in ordered:
        region = t.region_of(ln)
        before(rank.get(region, len(rank)))
        if layer.get(region, policy.layer(None)) in layers:
            if region in tables or region in formulas:
                if region not in done:
                    done.add(region)
                    out.append(whole(region))
            else:
                s = line_text(t, ln, illegible)
                if s is not None:
                    out.append(s)
        if last.get(region) == ln.id:
            out.extend(described.pop(region, ()))
    before(len(rank) + 1)
    for ds in described.values():                  # the page's, and those of regions the order leaves out
        out.extend(ds)
    return "\n".join(out)


def line_text(t: Transcription, ln, illegible: dict[str, list[tuple[int, int]]]) -> str | None:
    """A line's text as scored: its reading, its illegible spans as U+FFFD, one per character."""
    s = t.text_of(ln)
    if s is None:
        return None
    for start, end in illegible.get(ln.id, ()):
        s = s[:start] + REPLACEMENT * (end - start) + s[end:]
    return s
