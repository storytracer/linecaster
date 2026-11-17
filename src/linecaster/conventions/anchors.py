"""Anchors by alignment: which characters of a source text the lines an importer read come from.

An importer that turns a source into text through a processor it does not control (a template engine, a converter)
knows the source only before and the text only after. It describes what the processor saw as a ``SourceMap``:
pieces of text, each either the source verbatim (every character maps to its own position) or opaque (the output
of one call, which maps as a whole to the call's span). ``SourceMap.anchors(lines)`` aligns the lines, in reading
order, with the map's text (a monotonic alignment, rapidfuzz's Indel opcodes) and gives each line the span of the
source its matched characters come from; a line with no matched character has none.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from linecaster.data.transcription import Anchor


@dataclass
class SourceMap:
    """A text and, per character, the span of the source it comes from."""

    text: str = ""
    starts: list[int] = field(default_factory=list)
    ends: list[int] = field(default_factory=list)

    def verbatim(self, text: str, start: int) -> "SourceMap":
        """Appends source text as it stands at ``start``."""
        self.text += text
        self.starts += range(start, start + len(text))
        self.ends += range(start + 1, start + len(text) + 1)
        return self

    def opaque(self, text: str, start: int, end: int) -> "SourceMap":
        """Appends text that the source's ``[start, end)`` produced as a whole (a template call's output)."""
        self.text += text
        self.starts += [start] * len(text)
        self.ends += [end] * len(text)
        return self

    def anchors(self, lines: list[str]) -> list[Anchor | None]:
        """Each line's span of the source, aligned in order; ``None`` where no character of it is found."""
        from rapidfuzz.distance import Indel

        joined = "\n".join(lines)
        bounds, k = [], 0
        for line in lines:
            bounds.append((k, k + len(line)))
            k += len(line) + 1
        lo: list[int | None] = [None] * len(lines)
        hi: list[int | None] = [None] * len(lines)
        li = 0
        for op in Indel.opcodes(joined, self.text):
            if op.tag != "equal":
                continue
            for j in range(op.src_end - op.src_start):
                a = op.src_start + j
                while li < len(bounds) and a >= bounds[li][1]:
                    li += 1
                if li >= len(bounds):
                    break
                if a < bounds[li][0] or joined[a].isspace():
                    continue
                b = op.dest_start + j
                s, e = self.starts[b], self.ends[b]
                lo[li] = s if lo[li] is None else min(lo[li], s)
                hi[li] = e if hi[li] is None else max(hi[li], e)
        return [Anchor(start=a, end=b) if a is not None else None for a, b in zip(lo, hi)]
