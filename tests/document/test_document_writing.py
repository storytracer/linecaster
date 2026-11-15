"""Languages and writing directions in the document: built from what a transcription records (an HTML page's
``lang``, ``dir`` and ``writing-mode``), written as HTML's ``lang``, ``dir`` and ``writing-mode``, kept in the JSON,
and left out where nothing records them."""
from lxml import html

from linecaster.data import Annotator, Source, Transcription
from linecaster.document import build_document, from_json, to_html, to_json, to_markdown, to_text
from linecaster.formats.html import HtmlConverter

PAGE = """<html lang="en"><body>
<h2>A heading</h2>
<p>English text with <span lang="de">ein Wort</span> in it.<aside role="doc-footnote" lang="fr">Une note.</aside></p>
<p lang="ar" dir="rtl">نص عربي</p>
<div style="writing-mode: vertical-rl" lang="ja"><p>縦書きの文章</p></div>
</body></html>"""


def transcription(page: str = PAGE) -> Transcription:
    t = Transcription(source=Source(kind="ground_truth", format="html"))
    people = t.add_annotator(Annotator(kind="human", step="transcription", name="editors"))
    rules = t.add_annotator(Annotator(kind="rule", step="import", name="html", engine="import.html.v1"))
    return HtmlConverter().read(html.fromstring(page), t, people, rules).transcription


def test_the_document_carries_what_the_page_records():
    doc = build_document(transcription())
    assert doc.language == "en" and doc.direction is None
    by_text = {b.text: b for b in doc.blocks}
    assert (by_text["A heading"].language, by_text["A heading"].direction) == (None, None)
    assert (by_text["نص عربي"].language, by_text["نص عربي"].direction) == ("ar", "horizontal-rl")
    assert (by_text["縦書きの文章"].language, by_text["縦書きの文章"].direction) == ("ja", "vertical-rl")
    assert by_text["Une note."].language == "fr"
    para = by_text["English text with ein Wort in it."]
    assert [(para.text[s.start:s.end], s.language) for s in para.spans] == [("ein Wort", "de")]


def test_html_writes_lang_dir_and_writing_mode():
    out = to_html(build_document(transcription()))
    assert '<html lang="en">' in out
    assert "<h3>A heading</h3>" in out
    assert '<p>English text with <span lang="de">ein Wort</span> in it.</p>' in out
    assert '<aside role="doc-footnote" lang="fr"><p>Une note.</p></aside>' in out
    assert '<p lang="ar" dir="rtl">نص عربي</p>' in out
    assert '<p lang="ja" style="writing-mode: vertical-rl">縦書きの文章</p>' in out


def test_a_right_to_left_document_marks_its_left_to_right_blocks():
    doc = build_document(transcription('<html dir="rtl" lang="he"><body><p>שלום</p>'
                                       '<p dir="ltr" lang="en">Hello</p></body></html>'))
    assert (doc.language, doc.direction) == ("he", "horizontal-rl")
    out = to_html(doc)
    assert '<html lang="he" dir="rtl">' in out
    assert "<p>שלום</p>" in out and '<p lang="en" dir="ltr">Hello</p>' in out


def test_json_keeps_the_fields_and_leaves_out_unstated_ones():
    doc = build_document(transcription())
    again = from_json(to_json(doc))
    assert again == doc and to_html(again) == to_html(doc)
    plain = to_json(build_document(transcription("<html><body><p>Plain text.</p></body></html>")))
    assert '"language"' not in plain and '"direction"' not in plain


def test_markdown_and_text_do_not_change():
    doc = build_document(transcription())
    assert "lang" not in to_markdown(doc) and "<" not in to_text(doc)


def test_a_span_of_another_direction_is_written_as_one():
    from linecaster.data import Annotator, Transcription
    from linecaster.document import Document
    from linecaster.document.builder import build_document
    from linecaster.document.serialize import to_html

    t = Transcription()
    a = t.add_annotator(Annotator(step="transcription", name="people", kind="human"))
    t.add_region(a, "r0", role="paragraph")
    t.add_line(a, "l0", region="r0", text="The word שלום means peace.")
    t.classify(a, "l0[9:13]", "direction", "horizontal-rl")
    t.classify(a, "l0[9:13]", "language", "he")
    doc = build_document(t)
    assert '<p>The word <span lang="he" dir="rtl">שלום</span> means peace.</p>' in to_html(doc)
    back = Document.model_validate_json(doc.model_dump_json())
    assert [s.direction for s in back.blocks[0].spans] == [None, "horizontal-rl"]
    assert '"direction": null' not in doc.model_dump_json(indent=1)       # unstated: left out


def test_a_run_of_another_direction_is_one_isolate_whatever_its_formatting():
    from linecaster.data import SourceDocument
    from linecaster.document.builder import build_document
    from linecaster.document.serialize import to_html
    from linecaster.engines.importers import HtmlImporter

    t = HtmlImporter()(SourceDocument(data='<p>The phrase <span dir="rtl">שלום <b>עולם</b></span> and '
                                           '<i lang="de">ein <b>Wort</b></i>.</p>'))
    assert ('<p>The phrase <span dir="rtl">שלום <b>עולם</b></span> and <span lang="de"><i>ein </i><b><i>Wort</i></b>'
            '</span>.</p>') in to_html(build_document(t))
