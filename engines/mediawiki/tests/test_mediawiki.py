"""linecaster-mediawiki on a synthetic wiki: a dump written for the test (a template, a Lua module, a style sheet),
taken in by ``intake``, and Page: pages read with conventions of the test's own."""
from __future__ import annotations

import pytest

from linecaster.data import SourceDocument
from linecaster.engines.api import ConventionsDoc, resolve_conventions as resolve

DUMP = """<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/" version="0.11">
<siteinfo><sitename>Example</sitename><dbname>enexamplewiki</dbname><base>https://wiki.example.org/</base>
<case>first-letter</case><namespaces>
<namespace key="0" case="first-letter" /><namespace key="6" case="first-letter">File</namespace>
<namespace key="10" case="first-letter">Template</namespace><namespace key="14" case="first-letter">Category</namespace>
<namespace key="104" case="first-letter">Page</namespace><namespace key="828" case="first-letter">Module</namespace>
</namespaces></siteinfo>
<page><title>Template:Head</title><ns>10</ns><id>1</id><revision><id>11</id><model>wikitext</model><text>{template}</text></revision></page>
<page><title>Template:Head/styles.css</title><ns>10</ns><id>2</id><revision><id>12</id><model>sanitized-css</model><text>.x-shout {{ text-transform: uppercase }}</text></revision></page>
<page><title>Template:End</title><ns>10</ns><id>3</id><revision><id>13</id><model>wikitext</model><text>&lt;div class="x-end"&gt;&lt;/div&gt;</text></revision></page>
<page><title>Module:Twice</title><ns>828</ns><id>4</id><revision><id>14</id><model>Scribunto</model><text>local p = {{}}
function p.twice(frame) return frame.args[1] .. frame.args[1] end
return p</text></revision></page>
<page><title>Template:Twice</title><ns>10</ns><id>5</id><revision><id>15</id><model>wikitext</model><text>{{{{#invoke:Twice|twice|{{{{{{1}}}}}}}}}}</text></revision></page>
<page><title>Module:Wikidata link</title><ns>828</ns><id>6</id><revision><id>16</id><model>Scribunto</model><text>local p = {{}}
function p.link(frame)
  local id = frame.args.wikidata
  if not mw.wikibase.isValidEntityId(id) then return "&lt;span class='error'&gt;invalid&lt;/span&gt;" end
  if not mw.wikibase.entityExists(id) then return "&lt;span class='error'&gt;missing&lt;/span&gt;" end
  local label = mw.wikibase.getLabel(id)
  if frame.args.label ~= '' then label = frame.args.label end
  local site = mw.wikibase.getSitelink(id, 'enwiki') or 'https://example.org/?q=' .. id
  return '[' .. site .. ' ' .. label .. ']'
end
return p</text></revision></page>
<page><title>Template:Box</title><ns>10</ns><id>8</id><revision><id>18</id><model>wikitext</model><text>&lt;div class="x-box"&gt;{{{{{{1}}}}}}&lt;/div&gt;</text></revision></page>
<page><title>Template:Wdl</title><ns>10</ns><id>7</id><revision><id>17</id><model>wikitext</model><text>{{{{#invoke:Wikidata link|link|wikidata={{{{{{1|}}}}}}|label={{{{{{2|}}}}}} }}}}</text></revision></page>
</mediawiki>
""".format(template="&lt;templatestyles src=\"Head/styles.css\" /&gt;&lt;div class=\"x-head\"&gt;&lt;div "
                    "class=\"x-cell\"&gt;{{{1}}}&lt;/div&gt;&lt;div class=\"x-cell\"&gt;&lt;span class=\"x-shout\"&gt;"
                    "{{{2}}}&lt;/span&gt;&lt;/div&gt;&lt;/div&gt;")

CONVENTIONS = {"schema": "linecaster.conventions/1", "id": "example", "edition": 1, "format": "html",
               "description": "the test wiki's conventions", "rules": [
                   {"id": "head-cells", "match": {"kind": "tree", "css": ".x-cell"}, "decision": "cell",
                    "why": "the running head's cells"},
                   {"id": "end", "match": {"kind": "tree", "css": ".x-end"}, "decision": "break",
                    "why": "the paragraph ends on this page"}]}

PAGE = ('<noinclude><pagequality level="3" user="Someone" />{{Head|12|The title}}</noinclude>'
        "First paragraph with ''italic'' text and a note.<ref>The note's text.</ref>\n\n"
        "Second paragraph, {{Twice|ab}} and [[Link|a label]].[[Category:Example]]"
        "<noinclude>{{End}}</noinclude>")


@pytest.fixture(autouse=True, scope="module")
def no_network():
    """The importer reads no network: any connection is an error."""
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError(f"a network connection: {args}")

    saved = socket.socket.connect
    socket.socket.connect = refuse
    yield
    socket.socket.connect = saved


@pytest.fixture(scope="module")
def site(tmp_path_factory, no_network):
    from linecaster_mediawiki.intake import intake
    from linecaster_mediawiki import Site

    import bz2

    folder = tmp_path_factory.mktemp("site")
    dump = folder / "dump.xml.bz2"                          # wikitextprocessor reads bzip2 dumps
    dump.write_bytes(bz2.compress(DUMP.encode("utf-8")))
    return Site(intake(folder / "site", [dump], texvc=False))     # texvc: its own tests


@pytest.fixture(scope="module")
def reading(site):
    from linecaster_mediawiki import PageReader

    c = resolve("example@1", lambda ref: ConventionsDoc.model_validate(CONVENTIONS))
    return PageReader(site, c).read(PAGE, "Page:Example.djvu/12", revision="99")


def test_a_page_read_through_its_templates_and_modules(reading):
    t = reading.transcription
    texts = {ln.region: ln.reading.text for ln in t.lines}
    order = [r for r in t.order().regions if r in texts]
    assert [texts[r] for r in order] == ["12", "THE TITLE", "First paragraph with italic text and a note.",
                                         "The note's text.", "Second paragraph, abab and a label."]
    assert [t.role(r) for r in order] == ["header", "header", "paragraph", "footnote", "paragraph"]
    assert reading.ends_paragraph and not reading.unexpanded
    people, rules = t.annotators
    assert (people.kind, people.settings) == ("human", {"review": "proofread"})
    assert rules.conventions == "example@1" and rules.measurements["rules_matched"] == {"end": 1, "head-cells": 2}
    assert t.source.revision == "99" and t.source.format == "mediawiki"


def test_lines_are_anchored_in_the_revision(reading):
    t = reading.transcription
    for ln in t.lines:
        assert ln.anchor is not None, ln.reading.text
    first = next(ln for ln in t.lines if ln.reading.text.startswith("First"))
    assert PAGE[first.anchor.start:first.anchor.end].startswith("First paragraph with ''italic''")
    head = next(ln for ln in t.lines if ln.reading.text == "THE TITLE")
    assert "{{Head|12|The title}}" in PAGE[head.anchor.start:head.anchor.end]


def test_the_engine_reads_a_source_document(site):
    from linecaster_mediawiki import MediaWikiImporter

    from linecaster.testing import check_engine

    engine = MediaWikiImporter(site=str(site.folder))
    t = engine(SourceDocument(data=PAGE, record="Page:Example.djvu/12", revision="99"))
    assert t.source.kind == "ground_truth" and t.annotators[1].engine == "import.mediawiki.v1"
    assert any(ln.reading.text == "Second paragraph, abab and a label." for ln in t.lines)
    with pytest.raises(ValueError, match="title"):
        engine(SourceDocument(data=PAGE))
    check_engine(MediaWikiImporter, options={"site": str(site.folder)},
                 source=SourceDocument(data=PAGE, record="Page:Example.djvu/12"))


def test_wikidata_is_never_asked(site):
    """A Wikidata link prints the text its call brings; one that needs Wikidata's label prints none (its module
    fails: a software message, removed); the ids asked about are recorded."""
    from linecaster_mediawiki import PageReader

    c = resolve("mediawiki@1", lambda ref: ConventionsDoc.model_validate(
        {"schema": "linecaster.conventions/1", "id": "mediawiki", "edition": 1, "format": "html",
         "description": "software messages", "rules": [{"id": "errors", "match": {"kind": "tree", "css": ".error"},
                                                        "decision": "remove", "params": {"reason": "error"},
                                                        "why": "the software's messages"}]}))
    r = PageReader(site, c).read("<noinclude></noinclude>By {{wdl|Q868|Aristotle}} and {{wdl|Q1}}, not "
                                 "{{wdl|X9|Nobody}}.<noinclude></noinclude>", "Page:Example.djvu/3")
    t = r.transcription
    assert [ln.reading.text for ln in t.lines if ln.region in t.order().regions] == ["By Aristotle and , not ."]
    assert r.wikidata == ["Q1", "Q868"] and t.annotators[1].measurements["wikidata"] == ["Q1", "Q868"]


def test_a_formula_is_no_wikitext_inside_a_template(site):
    """As in MediaWiki, a formula's ``}}``, ``|`` and ``''`` are the formula's, also in a template's argument."""
    from linecaster_mediawiki import PageReader

    tex = r"\overline{\frac{a}{b}} = y''_1 + |x|"
    t = PageReader(site).read(f"<noinclude></noinclude>A {{{{Box|<math>{tex}</math>}}}} and <math>{tex}</math>."
                              "<noinclude></noinclude>", "Page:Example.djvu/4").transcription
    assert [f.latex for f in t.formulas] == [tex, tex]


class FakeTexvc:
    r"""texvc as the reader asks it: \Mu is \mathrm {M}, \bad is rejected, the rest as written."""

    def check(self, tex):
        return None if r"\bad" in tex else tex.replace(r"\Mu", r"\mathrm {M}")


def test_formulas_as_texvc_writes_them(site):
    """A formula's LaTeX is texvc's, the TeX as written its source; what texvc rejects stays as written, recorded."""
    from linecaster_mediawiki import PageReader
    from linecaster_mediawiki import site as site_module

    key = ("texvc", site.folder.resolve())
    site_module._CONTEXTS[key] = FakeTexvc()
    try:
        t = PageReader(site).read(r"<noinclude></noinclude>A <math>\Mu + x</math>, <math>y</math> and "
                                  r"<math>\bad</math>.<noinclude></noinclude>", "Page:Example.djvu/5").transcription
    finally:
        del site_module._CONTEXTS[key]
    assert [(f.latex, f.source) for f in t.formulas] == [(r"\mathrm {M} + x", r"\Mu + x"), ("y", None),
                                                         (r"\bad", None)]
    assert [ln.reading.text for ln in t.lines] == [r"A $\mathrm {M} + x$, $y$ and $\bad$."]
    rules = t.annotators[1]
    assert rules.measurements["texvc_rejected"] == [r"\bad"] and rules.settings["texvc"].startswith("mathoid-texvcjs")


@pytest.mark.network
def test_texvcjs_as_installed(tmp_path):
    """The pinned texvcjs, installed from the package registry as intake installs it."""
    from linecaster_mediawiki.texvc import Texvc, install

    install(tmp_path)
    t = Texvc(tmp_path)
    assert t.installed
    assert t.check(r"\overline\frac{a}{b} + \Mu") == r"{\overline {\frac {a}{b}}}+\mathrm {M} "
    assert t.check(r"\begin{align} a&=b \end{align}") == r"{\begin{aligned}a&=b\end{aligned}}"
    assert t.check(r"\undefinedcommand") is None


def test_each_part_starts_a_line(site):
    """A header or footer line that starts with a space is preformatted; the part after it starts a line of its own
    (ProofreadPage parses the parts apart), so the body is the body."""
    from linecaster_mediawiki import PageReader
    from linecaster_mediawiki.proofread import FOOT_START, HEAD_END

    t = PageReader(site).read("<noinclude><pagequality level=\"3\" user=\"x\" />\n {{Head|12|The title}}</noinclude>"
                              "Body text that runs on.\n\nA second paragraph.<noinclude> 13</noinclude>",
                              "Page:Example.djvu/6").transcription
    texts = [(t.role(ln.region), ln.reading.text) for ln in t.lines]
    assert ("paragraph", "Body text that runs on.") in texts and ("paragraph", "A second paragraph.") in texts
    assert not any(HEAD_END in x or FOOT_START in x for _, x in texts)


def test_a_table_across_parts_is_the_bodys(site):
    """A header that opens a table the page continues, and a footer that closes it: the table is the body's, and so
    is the text after it (the parser drops what stands between a table's start and its first row)."""
    from linecaster_mediawiki import PageReader

    t = PageReader(site).read("<noinclude><pagequality level=\"3\" user=\"x\" />{{Head|12|The title}}\n{| class=\"k\""
                              "</noinclude>\n|-\n|a cell||b cell\n|}\n\nA body paragraph.\n\n{|\n|-\n|c cell"
                              "<noinclude>\n|}</noinclude>", "Page:Example.djvu/7").transcription
    roles = {ln.reading.text: t.role(ln.region) for ln in t.lines}
    assert roles["A body paragraph."] == "paragraph" and roles["12"] == "header"
    assert all(t.role(tb.target) == "table" for tb in t.tables) and len(t.tables) == 2


def test_parts_and_top_level_calls():
    from linecaster_mediawiki import PageSource, top_level_calls

    ps = PageSource.from_revision(PAGE)
    assert PAGE[:ps.header_end].endswith("</noinclude>") and PAGE[ps.footer_start:].startswith("<noinclude>{{End}}")
    assert ps.quality == 3
    text = "a {{x|{{y}}}} b {{{p|{{z}}}}} {{#if:1|c}} <!-- {{no}} --> <nowiki>{{no}}</nowiki>"
    assert [text[a:b] for a, b in top_level_calls(text)] == ["{{x|{{y}}}}", "{{z}}", "{{#if:1|c}}"]


def test_pages_of_an_item_are_linked_where_a_paragraph_runs_on(site):
    from linecaster_mediawiki import PageReader, link_pages

    reader = PageReader(site)
    first = "<noinclude></noinclude>A paragraph that runs<noinclude></noinclude>"
    second = "<noinclude></noinclude>on to the next page.\n\nAnother one.{{End}}<noinclude></noinclude>"
    pages = [(f"p{i}", reader.read(w, f"Page:Example.djvu/{i}").transcription) for i, w in enumerate((first, second))]
    assert link_pages(pages) == 1
    t0, t1 = pages[0][1], pages[1][1]
    assert [(x.kind, x.target) for x in t0.links] == [("runs_into", "p1#paragraph_0")]
    assert [(x.kind, x.target) for x in t1.links] == [("continues", "p0#paragraph_0")]


@pytest.mark.parametrize("first, second, joined", [
    # a block at the page's end, or at the next page's start, ends the paragraph
    ("A paragraph that runs", "<div class=\"c\">A CENTRED HEADING</div>\n\nText.", False),
    ("<div class=\"c\">THE TITLE</div>", "on to the next page.", False),
    # a wrapper the header opens and the footer closes is the page's own view: the paragraphs inside run on
    ("<noinclude><div class=\"j\"></noinclude>A paragraph that runs<noinclude></div></noinclude>",
     "<noinclude><div class=\"j\"></noinclude>on to the next page.<noinclude></div></noinclude>", True),
    # nested wrappers too
    ("<noinclude><div class=\"q\"><div class=\"f\"></noinclude>A paragraph that runs"
     "<noinclude></div></div></noinclude>",
     "<noinclude><div class=\"q\"><div class=\"f\"></noinclude>on to the next page."
     "<noinclude></div></div></noinclude>",
     True),
    # the page's frame (a one-cell table the header opens and the footer closes) is unwrapped
    ("<noinclude>{| class=\"frame\"\n|-\n|</noinclude>A paragraph that runs<noinclude>\n|}</noinclude>",
     "<noinclude>{| class=\"frame\"\n|-\n|</noinclude>on to the next page.<noinclude>\n|}</noinclude>", True),
    # a block the page opens and does not close goes on onto the next page, which closes it
    ("<div class=\"b\">\nA paragraph that runs", "on to the next page.</div>\n\nText.", True),
    # a block the header reopens and the body closes ends on this page
    ("<noinclude><div class=\"b\"></noinclude>Its last line.</div>", "Next page's paragraph.", False),
])
def test_a_paragraph_runs_on_only_from_text_into_text(site, first, second, joined):
    """ProofreadPage joins a main-namespace page's pages with a space: text continues text, a block ends it."""
    from linecaster_mediawiki import PageReader, link_pages

    reader = PageReader(site)
    pages = [(f"p{i}", reader.read(w if w.startswith("<noinclude>") else f"<noinclude></noinclude>{w}",
                                   f"Page:Example.djvu/{i}").transcription) for i, w in enumerate((first, second))]
    assert (link_pages(pages) == 1) is joined
    assert not any("</div>" in ln.reading.text for _, t in pages for ln in t.lines)   # a stray end tag prints nothing


@pytest.mark.parametrize("first, second, cell", [
    # the footer closes the table, the header reopens it: the next page goes on with its rows
    ("{| class=\"t\"\n|-\n| a || b\n|-\n| c || d<noinclude>\n|}</noinclude>",
     "<noinclude>{| class=\"t\"\n</noinclude>|-\n| e || f\n|}", None),
    # the header ends inside a cell: the next page goes on with the last cell's text, in its column
    ("{| class=\"t\"\n|-\n| a || The entry that runs<noinclude>\n|}</noinclude>",
     "<noinclude>{| class=\"t\"\n|-\n| ||</noinclude>on to the next page.\n|-\n| c || d\n|}",
     ("table_0/r0c1", "p1#table_0/r0c1")),
])
def test_a_table_continues_across_the_page_break(site, first, second, cell):
    """A table one page leaves to the next is one table in the main namespace: each page reads its own, the links
    join them (an item's document builds one table)."""
    from linecaster_mediawiki import PageReader, link_pages

    reader = PageReader(site)
    pages = [(f"p{i}", reader.read(w if w.startswith("<noinclude>") else f"<noinclude></noinclude>{w}",
                                   f"Page:Example.djvu/{i}").transcription) for i, w in enumerate((first, second))]
    tables = [[r.id for r in t.regions if t.role(r.id) == "table"] for _, t in pages]
    assert [len(x) for x in tables] == [1, 1]
    assert link_pages(pages) == 1
    t0 = pages[0][1]
    assert ("runs_into", tables[0][0], f"p1#{tables[1][0]}") in [(x.kind, x.source, x.target) for x in t0.links]
    assert [(x.source, x.target) for x in t0.links if "/" in x.source] == ([cell] if cell else [])


def test_a_call_says_what_its_html_does_not(site):
    """The first element a template call writes carries its name and short parameters; conventions match them to
    join what each page writes whole (a stanza a template continues across the page break)."""
    from linecaster_mediawiki import PageReader, link_pages
    from linecaster_mediawiki.html import HtmlBuilder
    from linecaster_mediawiki.proofread import PageSource, mark_calls

    text, pos = PageSource.from_revision("{{Box|One line|end=follow}}").parsed()
    marked, _, calls = mark_calls(text, pos)
    w = site.wtp()
    w.start_page("Page:Example.djvu/9")
    box = HtmlBuilder(site, calls=calls).build(w.parse(marked, expand_all=True)).root.find(".//div")
    assert (box.get("data-mw-template"), box.get("data-mw-param-1"), box.get("data-mw-param-end")) == \
        ("Box", "One line", "follow")
    c = resolve("example@2", lambda ref: ConventionsDoc.model_validate(
        {"schema": "linecaster.conventions/1", "id": "example", "edition": 2, "format": "html",
         "description": "the test wiki's box across pages", "rules": [
             {"id": "box-continues", "decision": "continues", "why": "the box goes on from the previous page",
              "match": {"kind": "tree", "css": "[data-mw-template=Box][data-mw-param-start=follow]"}},
             {"id": "box-runs-on", "decision": "runs_on", "why": "the box goes on onto the next page",
              "match": {"kind": "tree", "css": "[data-mw-template=Box][data-mw-param-end=follow]"}}]}))
    texts = ("{{Box|A line that runs|end=follow}}", "{{Box|on to the next page.|start=follow}}")

    def read(reader):
        return [(f"p{i}", reader.read(f"<noinclude></noinclude>{x}", f"Page:Example.djvu/{i}").transcription)
                for i, x in enumerate(texts)]

    pages = read(PageReader(site, c))
    assert [len(t.lines) for _, t in pages] == [1, 1]                    # each page reads as it is
    assert link_pages(pages) == 1                                        # an item joins them
    assert link_pages(read(PageReader(site))) == 0                       # without the rules a block ends it


def test_a_literal_line_break_breaks_the_line(site):
    """A ``<br />`` the parser left as text is a line break."""
    from linecaster_mediawiki import PageReader

    t = PageReader(site).read("<noinclude></noinclude>{{Twice|ab}}<br />two</div><noinclude></noinclude>",
                              "Page:Example.djvu/8").transcription
    assert [ln.reading.text for ln in t.lines] == ["abab", "two"]
