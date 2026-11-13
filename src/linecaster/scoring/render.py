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
    """The text of ``t``'s regions in ``layers`` (a ``TEXTS`` name or the layers themselves), as laid out."""
    layers = TEXTS[layers] if isinstance(layers, str) else layers
    illegible = _illegible(t)
    layer = {r.id: policy.layer_of(t, r.id) for r in t.regions}
    tables = {tb.target: tb for tb in t.tables if tb.cells}
    out, done = [], set()
    for ln in t.ordered_lines():
        region = t.region_of(ln)
        if layer.get(region, policy.layer(None)) not in layers:
            continue
        if region in tables:
            if region not in done:
                done.add(region)
                out.append(render_table(tables[region]))
            continue
        s = t.text_of(ln)
        if s is None:
            continue
        for start, end in illegible.get(ln.id, ()):
            s = s[:start] + REPLACEMENT * (end - start) + s[end:]
        out.append(s)
    return "\n".join(out)
