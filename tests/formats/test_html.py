"""The HTML importer: HTML's semantics, DPUB-ARIA furniture and notes, CSS, and conventions' decisions."""
from lxml import html

from linecaster.data import Annotator, Source, Transcription
from linecaster.formats.html import HtmlImporter
from linecaster.markup import ConventionsDoc, resolve

PAGE = """<html><head><style>.caps { text-transform: uppercase }</style></head><body>
<header role="doc-pageheader"><div class="rh"><span class="cell">12</span><span class="cell">THE TITLE</span>
<span class="cell"></span></div></header>
<h2>Chapter <span class="caps">one</span></h2>
<p>A first paragraph with <i>italic</i> and a note<aside role="doc-footnote">The note's text.</aside>, then
a <span class="sic" title="corrected">corected</span> word and <math alttext="{\\displaystyle a\\,+\\,b}"></math>.</p>
<p>Second<br>line <span style="display:none">hidden</span><span style="visibility:hidden">x</span>end.
<span class="editlink">[edit]</span></p>
<table><tr><td rowspan="2">a</td><td>b</td></tr><tr><td>c <img src="File:Fig.png"></td></tr></table>
<div class="nop"></div>
<footer role="doc-pagefooter"><p>Foot</p></footer>
</body></html>"""

CONVENTIONS = {"schema": "linecaster.conventions/1", "id": "example", "edition": 1, "format": "html",
               "description": "test conventions", "rules": [
                   {"id": "head-cells", "match": {"kind": "tree", "css": ".rh > .cell"}, "decision": "cell",
                    "params": {"role": "header"}, "why": "running head cells"},
                   {"id": "sic", "match": {"kind": "tree", "css": ".sic"}, "decision": "edit",
                    "params": {"kind": "corrected", "attr": "title"}, "why": "a correction"},
                   {"id": "edit-links", "match": {"kind": "tree", "css": ".editlink"}, "decision": "remove",
                    "params": {"reason": "generated", "keep_text": True}, "why": "the wiki's links"},
                   {"id": "no-run-on", "match": {"kind": "tree", "css": ".nop"}, "decision": "break",
                    "why": "the paragraph does not run on"}]}


def read(page=PAGE, conventions=None):
    t = Transcription(source=Source(kind="ground_truth", format="html"))
    people = t.add_annotator(Annotator(kind="human", step="transcription", name="editors"))
    rules = t.add_annotator(Annotator(kind="rule", step="import", name="html", engine="import.html.v1"))
    return HtmlImporter(conventions).read(html.fromstring(page), t, people, rules)


def test_html_semantics_and_conventions():
    c = resolve("example@1", lambda ref: ConventionsDoc.model_validate(CONVENTIONS))
    r = read(conventions=c)
    t = r.transcription
    texts = {ln.id: ln.reading.text for ln in t.lines}
    order = t.order().regions
    roles = [t.role(x) for x in order]
    assert roles == ["header"] * 3 + ["heading", "paragraph", "footnote", "paragraph", "picture", "table", "footer"]
    head = order[0]
    assert [texts[ln.id] for ln in t.lines if t.region(ln.region).parent == head] == ["12", "THE TITLE"]
    assert texts["heading_0_l0"] == "Chapter ONE" and t.heading_level("heading_0") == 2
    assert texts["paragraph_0_l0"] == "A first paragraph with italic and a note, then a corected word and $a+b$."
    assert texts["footnote_0_l0"] == "The note's text."
    assert t.links[0].kind == "note_of" and t.links[0].target == "paragraph_0"
    assert [texts["paragraph_1_l0"], texts["paragraph_1_l1"]] == ["Second", "line end."]
    assert t.formulas[0].latex == "a+b" and t.edits[0].text == "corrected" and t.edits[0].kind == "corrected"
    ln = t.line("paragraph_0_l0")
    assert ln.reading.formatting[0].italic and ln.reading.formatting[0].charspan == [23, 29]
    table = t.tables[0]
    assert (table.num_rows, table.num_cols) == (2, 2) and [c.text for c in table.cells] == ["a", "b", "c"]
    assert t.region("picture_0").html__src == "File:Fig.png"
    removed = [x for x in t.regions if t.status(x.id) == "removed"]
    assert len(removed) == 1 and removed[0].id not in order
    assert t.classifications_of(removed[0].id, "status")[0].reason == "generated"
    assert r.ends_paragraph and r.coverage.matched["head-cells"] == 3
    assert r.coverage.unmapped == {".rh": 1, ".caps": 1}


def test_a_page_without_conventions_reads_by_html_alone():
    r = read("<body><p>One</p><p>Two runs on</p></body>")
    assert [ln.reading.text for ln in r.transcription.lines] == ["One", "Two runs on"]
    assert not r.ends_paragraph and not r.coverage.matched
