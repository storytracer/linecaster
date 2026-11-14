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
