"""One Page: page's revision read into a transcription.

The revision's parsed text (``PageSource.parsed``) is expanded and parsed by wikitextprocessor in the page's own
context (templates, parser functions and Lua modules from the wiki's pages), built into HTML (``HtmlBuilder``) and
read by linecaster's HTML importer under the wiki's conventions. Every line and region is then anchored in the
revision: the parsed text is described as verbatim pieces and, for each template call standing in it, the call's
own expansion, which stands for the call's span as a whole (``linecaster.markup.anchors``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from linecaster.data import Anchor, Annotator, Source, Transcription
from linecaster.engines.api import HtmlConverter, ResolvedConventions, SourceMap

from linecaster_mediawiki.html import HtmlBuilder
from linecaster_mediawiki.proofread import FOOT_START, HEAD_END, PageSource, mark_calls, top_level_calls
from linecaster_mediawiki.site import Site
from linecaster_mediawiki.texvc import VERSION as TEXVC

ENGINE = "import.mediawiki.v1"
#: ProofreadPage's levels as the review the people's annotator records
REVIEW = {0: "without_text", 1: "transcribed", 2: "problematic", 3: "proofread", 4: "validated"}
_TAGS = re.compile(r"<[^>]*>|'{2,}|\[\[[^|\]]*\||\]\]|\[\[")


#: elements of the body that are no block of the page's text
_NOT_TEXT = ("style", "link", "meta", "header", "footer", "aside")


def _text_children(el) -> list:
    return [c for c in el if isinstance(c.tag, str) and c.tag not in _NOT_TEXT
            and c.get("role") not in ("doc-footnote", "doc-pageheader", "doc-pagefooter")
            and "".join(c.itertext()).strip()]


def edges(root) -> tuple[bool, bool]:
    """Whether the page's body begins and ends with a plain paragraph: one the previous page's last paragraph can
    continue into, one that can run on into the next page's. ProofreadPage joins a main-namespace page's pages with a
    space, so text continues text, and a block (a centred heading, a table, a poem, a list) ends a paragraph. A block
    that goes on across the page break in the main namespace is no edge, its first or last block is: at the page's
    end one the page does not close (``data-unclosed``) or that the footer closes (``data-parts`` with ``footer``: the
    footer only closes it for the page's own view), at its start one the header opens (``data-parts`` with
    ``header``: reopened for the page's view, opened on an earlier page). One the body opens or closes is a block."""
    body = root.find("body")

    def plain(el, last: bool) -> bool:
        while el is not None:
            if el.tag == "p":
                return True
            parts = (el.get("data-parts") or "").split()
            if not (("footer" in parts or el.get("data-unclosed")) if last else "header" in parts):
                return False
            kids = _text_children(el)
            el = (kids[-1] if last else kids[0]) if kids else None
        return False

    kids = _text_children(body) if body is not None else []
    if not kids:
        return False, False
    return plain(kids[0], False), plain(kids[-1], True)


_ROW_SYNTAX = ("|", "!", "{|")
_LEAD = re.compile(r"^(?:\s|<templatestyles[^>]*/>|<!--.*?-->)*", re.S)   # what prints nothing before a row


def body_starts_row(text: str, expanded: dict[tuple[int, int], str]) -> bool:
    """Whether the body (after ``HEAD_END`` in the parsed ``text``) begins with a table's own syntax: a row, a cell or a
    table, written or from a call (its output in ``expanded``). In a table the header leaves open, text that does not
    goes on with the header's last cell, as the parser reads it."""
    k = text.find(HEAD_END)
    if k < 0:
        return False
    calls = {a: (b, v) for (a, b), v in expanded.items()}
    i = k + 1
    while True:
        while i < len(text) and text[i] in " \t\n":
            i += 1
        if text.startswith(_ROW_SYNTAX, i):
            return True
        if i not in calls:
            return False
        end, out = calls[i]
        out = _LEAD.sub("", out)
        if out:
            return out.startswith(_ROW_SYNTAX)
        i = end                                     # a call that prints nothing ({{nopt}}): what follows it decides


def table_edges(root, opens_table: bool, starts_row: bool = True) -> tuple[str | None, bool]:
    """How the page's body takes up and leaves a table across the page break, as the main namespace has one table:
    whether its first block continues the previous page's table (``rows``: the header reopens the table and the body
    goes on with its rows, ``opens_table`` or ``starts_row``; ``cell``: the body's first text goes on with the header's
    last cell, the previous page's last; else None), and whether its last block is a table the next page continues
    (the footer closes it, or the page leaves it open)."""
    body = root.find("body")
    kids = _text_children(body) if body is not None else []
    if not kids:
        return None, False
    first, last = kids[0], kids[-1]
    start = None
    if first.tag == "table":
        if opens_table:
            start = "rows"
        elif "header" in (first.get("data-parts") or "").split():
            start = "rows" if starts_row else "cell"
    runs_on = last.tag == "table" and ("footer" in (last.get("data-parts") or "").split()
                                       or bool(last.get("data-unclosed")))
    return start, runs_on


_NAMED = re.compile(r"""data-mw-template\s*=\s*["']?([^"'\]]+)""")


def named_templates(conventions: ResolvedConventions | None) -> frozenset[str]:
    """The templates the conventions' rules name (``[data-mw-template=...]``): their calls are marked wherever they
    stand, inside a line too (``{{hws}}`` at a line's end), for the rules to match the element each writes first."""
    if conventions is None:
        return frozenset()
    out = set()
    for r in conventions.rules:
        css = getattr(r.match, "css", None) or (r.match.get("css") if isinstance(r.match, dict) else None)
        out.update(m.group(1).strip() for m in _NAMED.finditer(css or ""))
    return frozenset(out)


@dataclass
class PageReading:
    transcription: Transcription
    ends_paragraph: bool
    unexpanded: list[str]
    wikidata: list[str]


class PageReader:
    """Reads Page: pages of one wiki under one set of resolved conventions."""

    def __init__(self, site: Site, conventions: ResolvedConventions | None = None):
        self.site = site
        self.conventions = conventions
        self.importer = HtmlConverter(conventions)
        self.inline = named_templates(conventions)

    def styles(self, src: str) -> str | None:
        """A TemplateStyles style sheet's text: ``src`` in the Template namespace unless it names one."""
        w = self.site.wtp()
        title = src if ":" in src else f"Template:{src}"
        ns_name, _, rest = title.partition(":")
        ns = next((int(k) for k, v in self.site.siteinfo["namespaces"].items()
                   if ns_name.lower() in {v.get("name", "").lower(), v.get("canonical", "").lower()}), 10)
        page = w.get_page(title, ns)
        return page.body if page is not None else None

    def read(self, wikitext: str, title: str, revision: str | None = None, record: str | None = None,
             dataset: str | None = None, parts: tuple[int, int] | None = None) -> PageReading:
        """The revision ``wikitext`` of the Page: page ``title``; ``parts``: where its header ends and its footer
        starts, where known (else from ProofreadPage's stored form)."""
        page = PageSource(wikitext, *parts) if parts else PageSource.from_revision(wikitext)
        text, pos = page.parsed()
        w = self.site.wtp()
        expanded = {}                                       # each top-level call's output, for the marks and anchors
        for a, b in top_level_calls(text):
            w.start_page(title)
            expanded[(a, b)] = w.expand(text[a:b], quiet=True)
        w.start_page(title)
        w.wikidata_asked = []
        def keep(a: int, b: int) -> bool:                  # a call whose output is a table's own syntax: no mark,
            return not _LEAD.sub("", expanded[(a, b)]).startswith(_ROW_SYNTAX)   # the syntax must begin its line

        marked, _, calls = mark_calls(text, pos, keep, self.inline)  # the calls' marks are for the build alone
        root = w.parse(marked, expand_all=True)
        built = HtmlBuilder(self.site, self.styles, calls).build(root)
        wikidata, w.wikidata_asked = sorted(set(w.wikidata_asked)), None
        t = Transcription(source=Source(kind="ground_truth", format="mediawiki", record=record or title,
                                        revision=revision, dataset=dataset))
        quality = page.quality
        people = t.add_annotator(Annotator(kind="human", step="transcription", name="editors",
                                           settings={"review": REVIEW[quality]} if quality in REVIEW else {}))
        c = self.conventions
        rules = t.add_annotator(Annotator(kind="rule", step="import", name="mediawiki", engine=ENGINE,
                                          conventions=c.ref if c else None,
                                          conventions_sha256=c.sha256 if c else None,
                                          settings={"texvc": TEXVC} if self.site.texvc() is not None else {}))
        reading = self.importer.read(built.root, t, people, rules)
        anchored = self.anchor(t, text, pos, title, expanded)
        opens_plain, closes_plain = edges(built.root)
        table_start, table_runs_on = table_edges(built.root, page.opens_table, body_starts_row(text, expanded))
        ends = not reading.runs_on and (reading.ends_paragraph or not closes_plain or built.closes_block)
        t.annotators[rules].measurements.update({**reading.coverage.measurements(), "anchored": anchored,
                                                 "ends_paragraph": ends,
                                                 "starts_paragraph": not (opens_plain or reading.continues)})
        if table_start:
            t.annotators[rules].measurements["table_continues"] = table_start
        if table_runs_on:
            t.annotators[rules].measurements["table_runs_on"] = True
        if built.unexpanded:
            t.annotators[rules].measurements["unexpanded"] = sorted(set(built.unexpanded))
        if built.texvc_rejected:
            t.annotators[rules].measurements["texvc_rejected"] = sorted(set(built.texvc_rejected))
        if wikidata:                                    # ids a module asked Wikidata about, unanswered
            t.annotators[rules].measurements["wikidata"] = wikidata
        return PageReading(t, ends, built.unexpanded, wikidata)

    def anchor(self, t: Transcription, text: str, pos: list[int], title: str,
               expanded: dict | None = None) -> float:
        """Anchors the lines and regions of ``t`` in the revision; returns the share of lines anchored."""
        w = self.site.wtp()
        m = SourceMap()                                 # verbatim pieces map character by character through pos
        k = 0
        for a, b in [*top_level_calls(text), (len(text), len(text))]:
            for i in range(k, a):
                ch = text[i]
                if ch in (HEAD_END, FOOT_START):
                    continue
                m.text += ch
                m.starts.append(pos[i])
                m.ends.append(pos[i] + 1)
            if b > a:
                if expanded is None or (a, b) not in expanded:
                    w.start_page(title)
                    out = w.expand(text[a:b], quiet=True)
                else:
                    out = expanded[(a, b)]
                out = _TAGS.sub("", out)
                m.opaque(out, pos[a], pos[b - 1] + 1)
            k = b
        lines = t.lines
        anchors = m.anchors([ln.reading.text if ln.reading else "" for ln in lines])
        for ln, an in zip(lines, anchors):
            ln.anchor = an
        spans: dict[str, list[int]] = {}
        for ln in lines:
            if ln.anchor is not None and ln.region:
                s = spans.setdefault(ln.region, [ln.anchor.start, ln.anchor.end])
                s[0], s[1] = min(s[0], ln.anchor.start), max(s[1], ln.anchor.end)
        for r in t.regions:
            if r.id in spans:
                r.anchor = Anchor(start=spans[r.id][0], end=spans[r.id][1])
        return sum(ln.anchor is not None for ln in lines) / len(lines) if lines else 1.0
