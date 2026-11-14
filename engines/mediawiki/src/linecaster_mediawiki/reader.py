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

ENGINE = "import.mediawiki.v1"
#: ProofreadPage's levels as the review the people's annotator records
REVIEW = {0: "without_text", 1: "transcribed", 2: "problematic", 3: "proofread", 4: "validated"}
_TAGS = re.compile(r"<[^>]*>|'{2,}|\[\[[^|\]]*\||\]\]|\[\[")


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
                                          conventions_sha256=c.sha256 if c else None))
        reading = self.importer.read(built.root, t, people, rules)
        anchored = self.anchor(t, text, pos, title)
        t.annotators[rules].measurements.update({**reading.coverage.measurements(), "anchored": anchored,
                                                 "ends_paragraph": reading.ends_paragraph})
        if built.unexpanded:
            t.annotators[rules].measurements["unexpanded"] = sorted(set(built.unexpanded))
        if wikidata:                                    # ids a module asked Wikidata about, unanswered
            t.annotators[rules].measurements["wikidata"] = wikidata
        return PageReading(t, reading.ends_paragraph, built.unexpanded, wikidata)

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
