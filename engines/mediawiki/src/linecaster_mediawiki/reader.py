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

from .html import HtmlBuilder
from .proofread import FOOT_START, HEAD_END, PageSource, top_level_calls
from .site import Site
from .texvc import VERSION as TEXVC

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
        w.start_page(title)
        w.wikidata_asked = []
        root = w.parse(text, expand_all=True)
        built = HtmlBuilder(self.site, self.styles).build(root)
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
        anchored = self.anchor(t, text, pos, title)
        opens_plain, closes_plain = edges(built.root)
        ends = reading.ends_paragraph or not closes_plain or built.closes_block
        t.annotators[rules].measurements.update({**reading.coverage.measurements(), "anchored": anchored,
                                                 "ends_paragraph": ends, "starts_paragraph": not opens_plain})
        if built.unexpanded:
            t.annotators[rules].measurements["unexpanded"] = sorted(set(built.unexpanded))
        if built.texvc_rejected:
            t.annotators[rules].measurements["texvc_rejected"] = sorted(set(built.texvc_rejected))
        if wikidata:                                    # ids a module asked Wikidata about, unanswered
            t.annotators[rules].measurements["wikidata"] = wikidata
        return PageReading(t, ends, built.unexpanded, wikidata)

    def anchor(self, t: Transcription, text: str, pos: list[int], title: str) -> float:
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
                w.start_page(title)
                out = _TAGS.sub("", w.expand(text[a:b], quiet=True))
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
