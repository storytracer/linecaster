"""The texts a benchmark scores, rendered from an annotation set under a rendering policy: ``full`` (the layers
``body`` and ``furniture``: everything printed on the page) and ``body`` (the body alone), as laid out (the read
lines in reading order, one per line; a region with a table as its table). What an annotator wrote about a figure
(descriptions) is in neither. A ground truth's illegible spans (``status`` ``illegible`` on a span of a line)
become U+FFFD, one per character; its corrections are not applied."""
from __future__ import annotations

from ..data.policy import DEFAULT_POLICY, RenderingPolicy
from ..data.refs import parse
from ..data.transcription import Transcription, render_table
from .lanes import REPLACEMENT

#: text name -> the layers it holds
TEXTS = {"full": ("body", "furniture"), "body": ("body",)}


def _illegible(t: Transcription) -> dict[str, list[tuple[int, int]]]:
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
    its place in the regions' reading order, before the first line of a later region."""
    layers = TEXTS[layers] if isinstance(layers, str) else layers
    illegible = _illegible(t)
    layer = {r.id: policy.layer_of(t, r.id) for r in t.regions}
    tables = {tb.target: tb for tb in t.tables if tb.cells}
    formulas = {f.target: f for f in t.formulas if f.target in layer and f.latex.strip()}
    rank = t.region_ranks()
    with_lines = {t.region_of(ln) for ln in t.lines}
    pending = [r.id for r in sorted(t.regions, key=lambda r: rank.get(r.id, len(rank)))
               if (r.id in tables or r.id in formulas) and r.id not in with_lines]
    out, done = [], set()

    def whole(region: str) -> str:
        return render_table(tables[region]) if region in tables else f"${formulas[region].latex.strip()}$"

    def before(r: int) -> None:
        while pending and rank.get(pending[0], len(rank)) < r:
            region = pending.pop(0)
            if layer.get(region, policy.layer(None)) in layers:
                out.append(whole(region))

    for ln in t.ordered_lines():
        region = t.region_of(ln)
        before(rank.get(region, len(rank)))
        if layer.get(region, policy.layer(None)) not in layers:
            continue
        if region in tables or region in formulas:
            if region not in done:
                done.add(region)
                out.append(whole(region))
            continue
        s = t.text_of(ln)
        if s is None:
            continue
        for start, end in illegible.get(ln.id, ()):
            s = s[:start] + REPLACEMENT * (end - start) + s[end:]
        out.append(s)
    before(len(rank) + 1)
    return "\n".join(out)
