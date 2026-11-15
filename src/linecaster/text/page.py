"""A page's literal text under a rendering policy: what a page file's md and txt hold when the page has no document
(lines only)."""
from __future__ import annotations

from ..data.policy import DEFAULT_POLICY, RenderingPolicy
from ..data.transcription import Transcription, render_table


def page_text(t: Transcription, policy: RenderingPolicy = DEFAULT_POLICY) -> str:
    """One page as read, as laid out, full page under ``policy``: the readings of its lines in reading order, a table
    region as its table (Markdown, HTML when a cell spans), the regions the policy puts nowhere left out
    (``Transcription.text`` under the default policy). Nothing is normalized: a strategy's character rules apply to
    it when a text is written."""
    tables = {tb.target: tb for tb in t.tables if tb.cells}
    hidden = {r.id for r in t.regions if policy.layer_of(t, r.id) == "none"}
    out, done = [], set()
    for ln in t.ordered_lines():
        region = t.region_of(ln)
        if region in hidden:
            continue
        if region in tables:
            if region not in done:
                done.add(region)
                out.append(render_table(tables[region]))
            continue
        text = t.text_of(ln)
        if text is not None:
            out.append(text)
    return "\n".join(out)


__all__ = ["page_text"]
