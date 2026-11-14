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
    return Site(intake(folder / "site", [dump]))


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


def test_parts_and_top_level_calls():
    from linecaster_mediawiki import PageSource, top_level_calls

    ps = PageSource.from_revision(PAGE)
    assert PAGE[:ps.header_end].endswith("</noinclude>") and PAGE[ps.footer_start:].startswith("<noinclude>{{End}}")
    assert ps.quality == 3
    text = "a {{x|{{y}}}} b {{{p|{{z}}}}} {{#if:1|c}} <!-- {{no}} --> <nowiki>{{no}}</nowiki>"
    assert [text[a:b] for a, b in top_level_calls(text)] == ["{{x|{{y}}}}", "{{z}}", "{{#if:1|c}}"]
