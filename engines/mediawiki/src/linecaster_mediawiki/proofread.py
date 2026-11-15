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
    def opens_table(self) -> bool:
        """Whether the header opens a table and ends before its next cell: the body goes on with the table's rows (the
        part boundary moves to the table's start, ``parsed``)."""
        return _open_table(self.wikitext[:self.header_end]) is not None

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
        part starts a line. A header that opens a table and ends before its next cell (after ``{|`` or a row's
        ``|-``) would put the marker where the parser drops text: the boundary moves to the table's start, and the
        table is the body's. One that ends inside a cell keeps its boundary (the marker stands in the cell's text:
        the page's frame, a one-cell table the footer closes, is unwrapped by the builder)."""
        w, h, f = self.wikitext, self.header_end, self.footer_start
        opened = _open_table(w[:h])
        if opened is not None:
            h = opened
        pieces =[(w[:h], 0, False), ("\n" + HEAD_END + "\n\n", h, True), (w[h:f], h, False),
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




#: a table's structural lines: its start, its end, a row's start, a caption, a cell (after whitespace and tags)
_TABLE_STRUCTURE = re.compile(r"(?m)^(?:\s|</?noinclude\s*>)*(\{\||\|\}|\|-|\|\+|\||!)")


def _open_table(text: str) -> int | None:
    """Where the outermost table that ``text`` opens and does not close starts (its line's start), when ``text`` ends
    before its next cell (its last structural line is the table's start or a row's ``|-``); else None."""
    stack: list[int] = []
    last = None
    for m in _TABLE_STRUCTURE.finditer(text):
        token = m.group(1)
        if token == "{|":
            stack.append(m.start())
        elif token == "|}":
            if stack:
                stack.pop()
        last = token
    return stack[0] if stack and last in ("{|", "|-") else None


#: around a top-level template call in the text the reader parses: its start (one character per call, its number
#: from ``CALL_FIRST``) and its end; private-use characters, as the part markers
CALL_END, CALL_FIRST = "\U000F7F03", 0xF7F10
CALL_MARKS = re.compile("([\U000F7F03\U000F7F10-\U000FFFFD])")
#: a parameter value as long as this or longer is content, not a setting: not written into the HTML
CALL_VALUE_LIMIT = 80


def call_parts(call: str) -> tuple[str, dict[str, str]]:
    """A template call's name, as MediaWiki resolves it (the ``Template:`` prefix dropped, underscores as spaces,
    the first letter upper case), and its short parameters (named, or positional by number; values under
    ``CALL_VALUE_LIMIT`` characters, stripped). A parser function's name keeps its ``#``."""
    inner = call[2:-2]
    parts, depth, k = [], 0, 0
    for i, ch in enumerate(inner):
        if inner.startswith(("{{", "[["), i):
            depth += 1
        elif inner.startswith(("}}", "]]"), i) and depth:
            depth -= 1
        elif ch == "|" and depth == 0:
            parts.append(inner[k:i])
            k = i + 1
    parts.append(inner[k:])
    name = " ".join(parts[0].replace("_", " ").split())
    if name.lower().startswith("template:"):
        name = name[len("template:"):].strip()
    name = name[:1].upper() + name[1:]
    params, n = {}, 0
    for p in parts[1:]:
        key, eq, value = p.partition("=")
        if eq and re.fullmatch(r"\s*[\w\- ]+\s*", key):
            key, value = key.strip(), value
        else:
            n += 1
            key, value = str(n), p
        value = value.strip()
        if len(value) < CALL_VALUE_LIMIT:
            params[key] = value
    return name, params


def mark_calls(text: str, pos: list[int], keep=None) -> tuple[str, list[int], list[tuple[str, dict[str, str]]]]:
    """``text`` with each top-level template call that begins a line (a block template, as ``{{ppoem}}`` stands)
    between its start mark and ``CALL_END``, the positions with the marks (each where its call starts or ends), and
    each call's name and short parameters (``call_parts``). A call inside a line is not marked (in a tag's attribute,
    a link or a table's attributes a mark would break what the parser reads), nor one inside a wikitext table (its
    output may be the table's own syntax, which must begin the line); ``keep(start, end)``, where given, decides the
    rest (the reader: not a call whose output is table syntax)."""
    tables = [(m.start(), m.group(1)) for m in _TABLE_STRUCTURE.finditer(text) if m.group(1) in ("{|", "|}")]
    out, out_pos, calls, k, t, depth = [], [], [], 0, 0, 0
    for a, b in top_level_calls(text):
        if len(calls) >= 0xFFFFD - CALL_FIRST:
            break
        while t < len(tables) and tables[t][0] < a:
            depth = depth + 1 if tables[t][1] == "{|" else max(0, depth - 1)
            t += 1
        line = text[text.rfind("\n", 0, a) + 1:a]
        if depth or line.strip(" \t" + HEAD_END + FOOT_START) or (keep is not None and not keep(a, b)):
            continue
        out.append(text[k:a])
        out_pos += pos[k:a]
        out.append(chr(CALL_FIRST + len(calls)) + text[a:b] + CALL_END)
        out_pos += [pos[a]] + pos[a:b] + [pos[b - 1] + 1]
        calls.append(call_parts(text[a:b]))
        k = b
    out.append(text[k:])
    out_pos += pos[k:]
    return "".join(out), out_pos, calls


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
