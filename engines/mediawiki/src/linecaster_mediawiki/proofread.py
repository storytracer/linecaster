"""ProofreadPage's ``Page:`` pages: their stored form, the text MediaWiki parses for them, and their parts.

A Page: page's revision stores ``<noinclude><pagequality level="N" user="..." />HEADER</noinclude>BODY<noinclude>
FOOTER</noinclude>``. MediaWiki parses ``HEADER + "\\n\\n" + BODY + FOOTER`` as one document (so a table opened in the
header can hold body rows, a template opened in the header and closed in the footer wraps the body), with
``<noinclude>`` and ``<onlyinclude>`` tags removed and ``<includeonly>`` elements removed. ``PageSource.parsed`` is
that text, with two private-use markers where the header ends and the footer starts, and per character its
position in the revision.

``top_level_calls`` finds the template calls and parser functions that stand in the text itself (not inside another
call): the importer expands each alone to know what it printed, for the anchors.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: private-use characters marking where the header ends and the footer starts in the parsed text
HEAD_END, FOOT_START = "\U000F7F01", "\U000F7F02"
_INCLUDEONLY = re.compile(r"<includeonly\s*>.*?(?:</includeonly\s*>|$)", re.S | re.I)
_NOINCLUDE_TAG = re.compile(r"</?(?:noinclude|onlyinclude)\s*/?>", re.I)
_QUALITY = re.compile(r"<pagequality\s+level\s*=\s*[\"']?(\d)", re.I)
_SKIP = re.compile(r"<!--.*?(?:-->|$)|<nowiki\s*>.*?(?:</nowiki\s*>|$)|<(math|pre|syntaxhighlight|source|score)"
                   r"\b[^>]*>.*?(?:</\1\s*>|$)", re.S | re.I)


@dataclass(frozen=True)
class PageSource:
    """One revision of a Page: page: its wikitext and where its header ends and its footer starts."""

    wikitext: str
    header_end: int
    footer_start: int

    @classmethod
    def from_revision(cls, wikitext: str) -> "PageSource":
        """The parts of a revision in ProofreadPage's stored form; text that is not in it is all body."""
        head, foot = 0, len(wikitext)
        if wikitext.lstrip().lower().startswith("<noinclude>"):
            close = wikitext.lower().find("</noinclude>")
            if close >= 0:
                head = close + len("</noinclude>")
        last = wikitext.lower().rfind("<noinclude>")
        if last >= head and wikitext.rstrip().lower().endswith("</noinclude>"):
            foot = last
        return cls(wikitext, head, foot)

    @property
    def quality(self) -> int | None:
        """The page's proofreading level (0-4) from its header's ``<pagequality>``."""
        m = _QUALITY.search(self.wikitext[:self.header_end])
        return int(m.group(1)) if m else None

    def parsed(self) -> tuple[str, list[int]]:
        """The text MediaWiki parses, the markers ``HEAD_END`` and ``FOOT_START`` at the parts' boundaries, and per
        character its position in the revision (a marker and the inserted separators map to where they stand).

        ProofreadPage keeps the header, the body and the footer apart and parses each from the start of a line: each
        marker stands on a line of its own, so a part's last line ends before it (a header line that starts with a
        space is preformatted, and its ``<pre>`` would otherwise hold the marker and the body after it) and the next
        part starts a line."""
        w, h, f = self.wikitext, self.header_end, self.footer_start
        pieces = [(w[:h], 0, False), ("\n" + HEAD_END + "\n\n", h, True), (w[h:f], h, False),
                  ("\n" + FOOT_START + "\n", f, True), (w[f:], f, False)]
        out: list[str] = []
        pos: list[int] = []
        for text, base, marker in pieces:
            if marker:
                out.append(text)
                pos += [base] * len(text)
                continue
            drop = sorted([(m.start(), m.end()) for m in _INCLUDEONLY.finditer(text)]
                          + [(m.start(), m.end()) for m in _NOINCLUDE_TAG.finditer(text)])
            k = 0
            for a, b in drop:
                if a < k:
                    continue
                out.append(text[k:a])
                pos += range(base + k, base + a)
                k = b
            out.append(text[k:])
            pos += range(base + k, base + len(text))
        return "".join(out), pos


def top_level_calls(text: str) -> list[tuple[int, int]]:
    """The spans ``[start, end)`` of the template calls and parser functions that stand in ``text`` itself, not
    inside another call; comments, ``<nowiki>`` and the tags whose content is not wikitext are skipped. Template
    parameters (``{{{...}}}``) are not calls."""
    skip = [(m.start(), m.end()) for m in _SKIP.finditer(text)]
    out: list[tuple[int, int]] = []
    stack: list[tuple[int, int]] = []           # (start, braces) of the open groups
    i, s, n = 0, 0, len(text)
    while i < n:
        if s < len(skip) and i >= skip[s][0]:
            i = max(i, skip[s][1])
            s += 1
            continue
        if text.startswith("{{", i):
            k = i
            while k < n and text[k] == "{":
                k += 1
            run = k - i
            braces = 3 if run >= 3 and run != 4 else 2
            stack.append((i + run - braces, braces))
            i += run if run in (2, 3) else braces
            continue
        if text.startswith("}}", i) and stack:
            start, braces = stack[-1]
            if text.startswith("}" * braces, i):
                stack.pop()
                i += braces
                if braces == 2 and not any(b == 2 for _, b in stack):
                    out.append((start, i))
                continue
            i += 2 if braces == 2 else 1
            continue
        i += 1
    return out
