"""The HTML importer: HTML's semantics, DPUB-ARIA furniture and notes, CSS, and conventions' decisions."""
import pytest
from lxml import html

from linecaster.data import Annotator, Source, Transcription
from linecaster.formats.html import HtmlConverter
from linecaster.conventions import ConventionsDoc, resolve

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

CONVENTIONS = {"schema": "linecaster.conventions", "id": "example", "format": "html",
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
    return HtmlConverter(conventions).read(html.fromstring(page), t, people, rules)


def test_html_semantics_and_conventions():
    c = resolve("example", lambda ref: ConventionsDoc.model_validate(CONVENTIONS))
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


def test_each_line_is_its_own_row():
    """A line of the source (a ``<br>`` inside a block) is a line break of the document, not a row joined with a
    space, as verse needs."""
    from linecaster.document import build_document

    t = read("<html><body><p>The night was dark,<br>the wind was cold,<br>and all the trees</p>"
             "<p>Prose in one line.</p></body></html>")
    paragraphs = [b.text for b in build_document(t.transcription).blocks if b.kind == "paragraph"]
    assert paragraphs == ["The night was dark,\nthe wind was cold,\nand all the trees", "Prose in one line."]
    from linecaster.document import to_markdown
    assert "The night was dark,\\\nthe wind was cold,\\\nand all the trees" in to_markdown(build_document(t.transcription))


def test_an_inline_formula_is_not_escaped_in_markdown():
    from linecaster.document import build_document, to_markdown

    t = read('<html><body><p>The sum <math alttext="{\\displaystyle v_{1}+v_{2}}"></math> of snake_case.</p></body></html>')
    md = to_markdown(build_document(t.transcription))
    assert "v_{1}" in md and "snake\\_case" in md


def test_markdown_knows_formulas_by_their_spans():
    """The document carries each inline formula as a span, so a dollar that is no formula can be written \\$, and
    the dialect's line breaks and displayed formulas follow the rules."""
    from linecaster.data.policy import MarkdownRules
    from linecaster.document import build_document, to_markdown

    t = read('<html><body><p>Another $50,000 for <math alttext="{\\displaystyle v_{1}}"></math> and $5.<br>'
             'A new line.</p></body></html>')
    doc = build_document(t.transcription)
    para = next(b for b in doc.blocks if b.kind == "paragraph")
    assert [para.text[s.start:s.end] for s in para.spans if s.formula] == ["$v_{1}$"]
    dialect = MarkdownRules(escape=False, escape_dollar=True, line_break="spaces", formula_display="$")
    assert to_markdown(doc, rules=dialect) == "Another \\$50,000 for $v_{1}$ and \\$5.  \nA new line."
    assert to_markdown(doc) == "Another $50,000 for $v_{1}$ and $5.\\\nA new line."



def test_a_table_cell_knows_its_formulas():
    """A cell's formulas are spans of its text, so a printed dollar in a cell is told apart from a formula: written
    \\$ by the rule in a table's HTML and in a table set as text, never paired with the next cell's dollar."""
    from linecaster.data.policy import DEFAULT_POLICY, MarkdownRules, TableRules
    from linecaster.document import build_document, table_html, to_markdown

    cell = '<td>Cost <math alttext="{\\displaystyle x}"></math> at $5</td>'
    t = read(f"<html><body><table><tr>{cell}<td>$0 40</td></tr><tr><td>a</td><td>b</td></tr></table>"
             "</body></html>").transcription
    first = t.tables[0].cells[0]
    assert first.text == "Cost $x$ at $5" and [first.text[a:e] for a, e in first.formulas] == ["$x$"]
    assert t.tables[0].cells[1].formulas == []
    rules = MarkdownRules(escape=False, escape_dollar=True)
    table = next(b for b in build_document(t).blocks if b.kind == "table")
    assert table_html(table, escape_dollar=True).startswith("<table><tr><td>Cost $x$ at \\$5</td><td>\\$0 40</td>")
    assert "<td>Cost $x$ at $5</td>" in table_html(table)
    assert "Cost $x$ at \\$5" in to_markdown(build_document(t), rules=rules)

    one = read(f"<html><body><table><tr>{cell}</tr></table></body></html>").transcription
    policy = DEFAULT_POLICY.model_copy(update={"tables": TableRules(single_cell="text"), "markdown": rules})
    para = next(b for b in build_document(one, policy=policy).blocks if b.kind == "paragraph")
    assert [para.text[s.start:s.end] for s in para.spans if s.formula] == ["$x$"]
    assert to_markdown(build_document(one, policy=policy), rules=rules) == "Cost $x$ at \\$5"


def test_a_line_edited_whole_keeps_its_spans():
    """A source's edit of a whole line is a span of the literal text; a strategy that applies it (here a correction:
    ``editors-corrections``) moves the line's formatting and formulas with their text; a span on removed text
    goes."""
    from linecaster.data.transcription import Edit
    from linecaster.document import build_document

    t = read('<html><body><p>The <i>food</i> <math alttext="{\\displaystyle x}"></math> <i>de-</i></p>'
             '</body></html>').transcription
    ln = t.lines[0]
    assert ln.reading.text == "The food $x$ de-"
    t.edits.append(Edit(annotator=0, target=ln.id, kind="corrected", text="The food $x$"))
    literal = next(b for b in build_document(t).blocks if b.kind == "paragraph")
    assert literal.text == "The food $x$ de-"                                  # literal: as read
    assert [(s.start, s.end, s.edit, s.edit_text) for s in literal.spans if s.edit] == [
        (0, 16, "corrected", "The food $x$")]
    from linecaster.document.strategy import apply

    para = next(b for b in apply(build_document(t), "editors-corrections").blocks if b.kind == "paragraph")
    assert para.text == "The food $x$"
    assert [(para.text[s.start:s.end], s.italic, s.formula) for s in para.spans] == \
        [("food", True, False), ("$x$", False, True)]


def test_a_dollar_in_a_block_without_formulas_is_escaped_by_the_rule():
    from linecaster.data.policy import MarkdownRules
    from linecaster.document import build_document, to_markdown

    doc = build_document(read("<html><body><p>Wages, $3.40; plumbers, $4.</p></body></html>").transcription)
    assert to_markdown(doc, rules=MarkdownRules(escape_dollar=True)) == "Wages, \\$3.40; plumbers, \\$4."


def test_a_running_head_below_the_bodys_text_is_body_text():
    """A row of cells without a role is the running head at the top of the body, but below a picture or text it is
    body text (a plate's caption set with the running head's template)."""
    rules = resolve("cells", lambda ref: ConventionsDoc.model_validate(
        {"schema": "linecaster.conventions", "id": "cells", "format": "html",
         "description": "rows of cells", "rules": [
             {"id": "cells", "match": {"kind": "tree", "css": ".rh > .cell"}, "decision": "cell",
              "why": "a running head's cells"}]}))
    row = '<div class="rh"><span class="cell">Drawn by A.</span><span class="cell">ROSA.</span></div>'
    top = read(f"<html><body>{row}<p>Text.</p></body></html>", rules).transcription
    plate = read(f'<html><body><figure><img src="File:Rosa.png"></figure>{row}</body></html>', rules).transcription
    assert [top.role(r.id) for r in top.regions][:3] == ["header", "header", "header"]
    assert [plate.role(r.id) for r in plate.regions] == ["picture", "paragraph", "paragraph", "paragraph"]


def test_the_conventions_transcription_is_the_sources_normalizations():
    """A conventions entry names the normalizations its source's transcription embodies (``transcription``): the
    nearest entry of the chain that states them, part of the hash; the importer copies them into
    ``Source.normalized``."""
    parent = {**CONVENTIONS, "id": "base", "rules": [], "transcription": ["nfc"]}
    child = {"schema": "linecaster.conventions", "id": "child", "format": "html", "extends": "base",
             "description": "a child", "transcription": ["nfc", "long-s"]}
    silent = {**child, "id": "silent", "transcription": None}
    docs = {d["id"]: ConventionsDoc.model_validate(d) for d in (parent, child, silent)}
    entry = docs.__getitem__
    assert resolve("child", entry).transcription == ("nfc", "long-s")
    assert resolve("silent", entry).transcription == ("nfc",)                     # the parent's
    assert resolve("child", entry).sha256 != resolve("silent", entry).sha256
    t = read(conventions=resolve("child", entry))
    assert t.transcription.source.normalized == ["nfc", "long-s"]
    assert read().transcription.source.normalized == []


def test_enwikisource_declares_its_transcription():
    from linecaster.catalog.registry import catalog

    c = catalog()
    assert c.conventions("enwikisource").transcription == ("nfc", "long-s", "ligatures", "r-rotunda", "divided-words")
    assert c.conventions("mediawiki").transcription == ("nfc",)


WRITING = """<html lang="en"><body>
<header role="doc-pageheader" lang="la">Liber primus</header>
<h2>A heading</h2>
<p>English text with <span lang="de">ein <i>deutsches</i> Wort</span> in it.<aside role="doc-footnote" lang="fr">Une
note.</aside></p>
<p lang="ar" dir="rtl">نص عربي <bdo dir="ltr">ABC</bdo></p>
<div style="writing-mode: vertical-rl" lang="ja"><p>縦書きの文章</p></div>
<p lang="en US">An ill-formed tag.</p>
</body></html>"""


def writing(t, scheme):
    return {c.target: c.value for c in t.classifications if c.scheme == scheme}


def test_lang_dir_and_writing_mode_are_recorded_where_they_differ():
    """The root's language and direction are the page's, a block's that differs its region's, inline runs' that
    differ from their line's a span's (consecutive runs merged, without spaces at either end); a ``lang`` on a page
    header or a note is read, an ill-formed one skipped and counted."""
    r = read(WRITING)
    t = r.transcription
    texts = {ln.id: ln.reading.text for ln in t.lines}
    assert texts["paragraph_0_l0"][18:36] == "ein deutsches Wort"
    assert writing(t, "language") == {"": "en", "header_0": "la", "paragraph_0_l0[18:36]": "de", "footnote_0": "fr",
                                      "paragraph_1": "ar", "paragraph_2": "ja"}
    assert writing(t, "direction") == {"paragraph_1": "horizontal-rl", "paragraph_1_l0[8:11]": "horizontal-lr",
                                       "paragraph_2": "vertical-rl"}
    assert texts["paragraph_1_l0"][8:11] == "ABC"
    assert t.language("paragraph_3_l0") == "en" and t.language("footnote_0_l0") == "fr"
    assert t.direction("paragraph_2_l0") == "vertical-rl" and t.direction("") is None
    assert r.ill_formed_languages == {"en US": 1}


def test_the_roots_dir_is_the_pages_and_auto_records_nothing():
    t = read('<html dir="rtl" lang="he"><body><p>שלום</p><p dir="ltr" lang="en">Hello</p>'
             '<p dir="auto">?</p></body></html>').transcription
    assert writing(t, "direction") == {"": "horizontal-rl", "paragraph_1": "horizontal-lr"}
    assert writing(t, "language") == {"": "he", "paragraph_1": "en"}


def test_a_language_reaches_notes_and_cells():
    t = read('<html><body><p lang="de">Text<aside role="doc-footnote">Fußnote.</aside></p>'
             '<table lang="fr"><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>'
             '</body></html>').transcription
    assert writing(t, "language") == {"paragraph_0": "de", "footnote_0": "de", "table_0": "fr"}


def test_auto_directionality_follows_the_text():
    from linecaster.data import SourceFile
    from linecaster.engines.importers import HtmlImporter

    t = HtmlImporter()(SourceFile(data='<html dir="rtl"><body><p dir="auto">English text</p><p>שלום</p>'
                                           '<p>English and <bdi>שלום עולם</bdi> here</p><p dir="auto">123</p>'
                                           '</body></html>'))
    assert [t.text_of(ln) for ln in t.lines][1] == "שלום"                 # text: parsed as the UTF-8 it is
    assert [(r.id, t.direction(r.id)) for r in t.regions] == [
        ("paragraph_0", "horizontal-lr"), ("paragraph_1", "horizontal-rl"), ("paragraph_2", "horizontal-rl"),
        ("paragraph_3", "horizontal-rl")]                                  # digits only: the page's
    spans = [(c.target, c.value) for c in t.classifications if c.scheme == "direction" and "[" in c.target]
    assert spans == []                     # the bdi's Hebrew in a right-to-left page: nothing differs


@pytest.mark.parametrize("html, directions", [
    ('<div dir="auto"><p>Hello</p><p>שלום</p></div>', []),                       # resolved once, on the div
    ('<ul dir="auto"><li>שלום</li><li>abc</li></ul>', [("list_item_0", "horizontal-rl"),
                                                      ("list_item_1", "horizontal-rl")]),
    ('<p dir="auto">abc<br>שלום</p>', []),
    ('<p dir="auto"><span dir="ltr">abc</span> שלום</p>', [("paragraph_0", "horizontal-rl"),
                                                          ("paragraph_0_l0[0:3]", "horizontal-lr")]),
    ('<p>Hi <bdi>user</bdi> there</p>', []),                                     # as inherited: nothing recorded
    ('<p dir="auto">Hello</p>', []),
    ('<p>Hi <bdi>שלום</bdi> there</p>', [("paragraph_0_l0[3:7]", "horizontal-rl")]),
])
def test_auto_directionality_is_resolved_on_its_element(html, directions):
    from linecaster.data import SourceFile
    from linecaster.engines.importers import HtmlImporter

    t = HtmlImporter()(SourceFile(data=html))
    assert [(c.target, c.value) for c in t.classifications if c.scheme == "direction"] == directions
