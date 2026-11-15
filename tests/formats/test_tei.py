"""The TEI P5 importer: a sourceDoc's surface, a text with its facsimile, a text without geometry, the inline markup
(choices, gaps, unclear text, formatting, furniture, languages, divided words), pages, and auto-detection."""
import pytest

from linecaster.data import SourceDocument
from linecaster.engines.importers import AutoImporter, TeiImporter
from linecaster.formats.tei import from_tei
from linecaster.formats.text import sniff
from linecaster.scoring import score_page
from linecaster.scoring.render import text as rendered

TEI = 'xmlns="http://www.tei-c.org/ns/1.0"'

#: a diplomatic page: a running header, a page number, two paragraphs and a note, in a surface's grid of half the
#: image's size
DIPLOMATIC = f"""<?xml version="1.0" encoding="UTF-8"?>
<TEI {TEI} xml:lang="en">
<teiHeader><fileDesc><titleStmt><title>A test page</title></titleStmt></fileDesc></teiHeader>
<sourceDoc><surface xml:id="s12" ulx="0" uly="0" lrx="1000" lry="1500">
 <graphic url="https://library.test/iiif/page12/full/full/0/default.jpg" width="2000px" height="3000px"/>
 <zone xml:id="rh" type="running-title" ulx="100" uly="40" lrx="700" lry="80">
  <line ulx="100" uly="40" lrx="700" lry="80">THE <hi rend="italic">HISTORY</hi> OF TESTS</line></zone>
 <zone xml:id="folio" type="pageNum" ulx="850" uly="40" lrx="900" lry="80">
  <line ulx="850" uly="40" lrx="900" lry="80">12</line></zone>
 <zone xml:id="p1" type="paragraph" points="100,100 900,100 900,250 100,250">
  <line xml:id="l1" points="100,100 900,100 900,140 100,140"><path points="100,135 900,135"/>It was a dark and
   exam-</line>
  <line xml:id="l2" ulx="100" uly="150" lrx="900" lry="190"><lb break="no"/>ple night when the</line>
  <line xml:id="l3" ulx="100" uly="200" lrx="900" lry="240">rain fell.</line>
 </zone>
 <zone xml:id="p2" type="paragraph" ulx="100" uly="300" lrx="900" lry="390">
  <line xml:id="l4" ulx="100" uly="300" lrx="900" lry="340">A second paragraph<hi rend="sup">1</hi> begins</line>
  <line xml:id="l5" ulx="100" uly="350" lrx="900" lry="390">here.</line>
 </zone>
 <zone xml:id="n1" type="note" ulx="100" uly="1300" lrx="900" lry="1340">
  <line xml:id="l6" ulx="100" uly="1300" lrx="900" lry="1340">1 A note at the foot.</line></zone>
</surface></sourceDoc>
</TEI>"""

#: a text with its facsimile: zones for a paragraph and its lines, two pages
FACSIMILE = f"""<TEI {TEI}>
<teiHeader/>
<facsimile>
 <surface xml:id="f1" ulx="0" uly="0" lrx="800" lry="1200"><graphic url="https://example.org/f1.png"/>
  <zone xml:id="zp" ulx="50" uly="100" lrx="750" lry="200"/>
  <zone xml:id="zl1" ulx="50" uly="100" lrx="750" lry="140"/>
  <zone xml:id="zl2" points="50,150 750,150 750,190 50,190"/>
 </surface>
 <surface xml:id="f2" lrx="600" lry="900"><zone xml:id="zq" ulx="10" uly="20" lrx="590" lry="60"/></surface>
</facsimile>
<text><body>
 <pb facs="#f1" n="1"/>
 <fw type="header">CHAPTER I.</fw>
 <p facs="#zp"><lb facs="#zl1"/>The first line with a mark<note place="foot">The note.</note>
 <lb facs="#zl2"/>and the <hi rend="bold">second</hi> line.</p>
 <fw type="catch">Next</fw>
 <pb facs="#f2" xml:id="pb2" n="2"/>
 <p facs="#zq">Page two.</p>
</body></text></TEI>"""

#: a text without geometry: a title page before the first pb, headings in divisions, a paragraph across a page
TEXT = f"""<TEI {TEI}><text><front><titlePage><titlePart>A Title</titlePart></titlePage></front><body>
<div><head>Book One</head><div><head>Chapter One</head>
<pb n="1" xml:id="page1"/>
<p>First line<lb/>second line, and the page <pb n="2"/>turns<lb/>here.</p>
<lg><l>A verse line</l><l>another</l></lg>
<p>Last <unknownElement type="x">kept</unknownElement> words.</p>
</div></div></body></text></TEI>"""

#: inline markup in a text: choices, gap, unclear, formatting, furniture, languages, a divided word
INLINE = f"""<TEI {TEI} xml:lang="en"><text><body>
<fw type="pageNum">7</fw><fw type="header">ON TESTS</fw>
<p>A <choice><sic>teh</sic><corr>the</corr></choice> word, <choice><expan>Doctor</expan><abbr>Dr.</abbr></choice>
Smith, <choice><orig>vvhich</orig><reg>which</reg></choice> is <hi rend="italic bold">set</hi> in
<foreign xml:lang="ar">مرحبا بكم</foreign> and <foreign xml:lang="grc">λόγος</foreign>;
<unclear reason="faded">dim</unclear> letters <gap reason="damage" extent="3 words"/> and a divid-<lb break="no"/>ed
word<lb/>end.</p>
<fw type="sig">A2</fw><fw type="catch">The</fw>
</body></text></TEI>"""


def texts(t) -> dict:
    return {ln.id: ln.reading.text for ln in t.lines}


# ------------------------------------------------------------------------------------------- the three forms


def test_a_diplomatic_page_reads_zones_lines_and_their_geometry():
    t = from_tei(DIPLOMATIC)
    assert (t.source.format, t.source.uri) == ("tei", "https://library.test/iiif/page12/full/full/0/default.jpg")
    assert (t.source.image_width, t.source.image_height) == (2000, 3000)
    assert t.order().regions == ["rh", "folio", "p1", "p2", "n1"]
    assert [t.role(r) for r in t.order().regions] == ["header", "page_number", "paragraph", "paragraph", "footnote"]
    assert t.region("rh").label == "running-title"
    assert t.region("p1").polygon == [[200.0, 200.0], [1800.0, 200.0], [1800.0, 500.0], [200.0, 500.0]]
    assert t.region("p2").box == [200.0, 600.0, 1600.0, 180.0]          # the surface's grid, scaled to the image
    lines = texts(t)
    assert [lines[x] for x in ("l1", "l2", "l3", "l6")] == ["It was a dark and exam-", "ple night when the",
                                                            "rain fell.", "1 A note at the foot."]
    assert lines["rh_l0"] == "THE HISTORY OF TESTS" and lines["folio_l0"] == "12"
    assert t.line("l1").baseline == [[200.0, 270.0], [1800.0, 270.0]] and t.line("l2").box == [200, 300, 1600, 80]
    assert [ln.region for ln in t.lines if ln.id.startswith("l")] == ["p1"] * 3 + ["p2"] * 2 + ["n1"]
    head = t.line("rh_l0").reading.formatting[0]
    assert head.italic and head.charspan == [4, 11]
    assert t.line("l4").reading.formatting[0].script == "super"
    assert t.language("") == "en" and t.classifications_of("p1", "language") == []
    assert [(e.target, e.kind, e.text) for e in t.edits] == [("l1[18:23]", "joined", "example"),
                                                            ("l2[0:3]", "joined", "example")]
    assert t.annotators[0].kind == "file" and t.annotators[0].name == "tei"


def test_a_zone_without_lines_and_a_line_on_the_surface():
    doc = f"""<TEI {TEI}><sourceDoc><surface>
     <line ulx="10" uly="10" lrx="90" lry="20"><fw type="pageNum">3</fw></line>
     <line ulx="10" uly="30" lrx="90" lry="40">A line of no zone</line>
     <zone type="column"><zone ulx="10" uly="50" lrx="90" lry="90">First<lb/>second</zone></zone>
     <zone type="figure" ulx="10" uly="100" lrx="90" lry="200"/>
    </surface></sourceDoc></TEI>"""
    t = from_tei(doc)
    order = t.order().regions
    assert [t.role(r) for r in order] == ["page_number", "paragraph", "picture"]   # the column holds zones only
    assert t.region(order[0]).box == [10.0, 10.0, 80.0, 10.0]
    free = [ln for ln in t.lines if ln.region is None]
    assert [ln.reading.text for ln in free] == ["A line of no zone"]
    assert [ln.reading.text for ln in t.lines if ln.region == order[1]] == ["First", "second"]
    assert (t.source.image_width, t.source.image_height) == (None, None)


def test_a_text_with_its_facsimile():
    t = from_tei(FACSIMILE, ground_truth=True)
    assert (t.source.kind, t.annotators[0].kind) == ("ground_truth", "human")
    assert (t.source.uri, t.source.image_width, t.source.image_height) == ("https://example.org/f1.png", 800, 1200)
    order = t.order().regions
    assert [t.role(r) for r in order] == ["header", "paragraph", "footnote", "catch_word"]
    p = order[1]
    assert t.region(p).box == [50.0, 100.0, 700.0, 100.0]
    lines = [ln for ln in t.lines if ln.region == p]
    assert [ln.reading.text for ln in lines] == ["The first line with a mark", "and the second line."]
    assert [ln.box for ln in lines] == [[50.0, 100.0, 700.0, 40.0], [50.0, 150.0, 700.0, 40.0]]
    assert lines[1].polygon == [[50.0, 150.0], [750.0, 150.0], [750.0, 190.0], [50.0, 190.0]]
    assert [(k.kind, k.source, k.target) for k in t.links] == [("note_of", order[2], p)]
    assert t.region(order[0]).box is None                       # no facs: no geometry
    for page in (2, "pb2", "f2"):
        second = from_tei(FACSIMILE, page=page)
        assert [ln.reading.text for ln in second.lines] == ["Page two."]
        assert (second.source.image_width, second.source.image_height) == (600, 900)
        assert second.regions[0].box == [10.0, 20.0, 580.0, 40.0]


def test_a_text_without_geometry_and_its_pages():
    first = from_tei(TEXT)                                      # the title page and headings before the first pb
    assert [(first.role(r), first.heading_level(r)) for r in first.order().regions] == [
        ("title", None), ("heading", 1), ("heading", 2)]
    assert all(ln.box is None for ln in first.lines)
    t = from_tei(TEXT, page=2)
    assert t.lines and t.lines == from_tei(TEXT, page="page1").lines
    assert [ln.reading.text for ln in t.lines] == ["First line", "second line, and the page"]
    third = from_tei(TEXT, page=3)
    assert [ln.reading.text for ln in third.lines] == ["turns", "here.", "A verse line", "another",
                                                        "Last kept words."]
    assert [third.role(r) for r in third.order().regions] == ["paragraph"] * 3
    with pytest.raises(ValueError, match="no page 4"):
        from_tei(TEXT, page=4)
    with pytest.raises(ValueError, match="nowhere"):
        from_tei(TEXT, page="nowhere")


# ------------------------------------------------------------------------------------------- inline markup


def test_choices_gaps_unclear_text_formatting_furniture_and_languages():
    t = from_tei(INLINE)
    order = t.order().regions
    assert [t.role(r) for r in order] == ["page_number", "header", "paragraph", "signature_mark", "catch_word"]
    lines = [ln for ln in t.lines if ln.region == order[2]]
    text = lines[0].reading.text
    assert text == ("A teh word, Dr. Smith, vvhich is set in مرحبا بكم and λόγος; dim letters and a divid-")
    assert [ln.reading.text for ln in lines[1:]] == ["ed word", "end."]
    lid = lines[0].id

    def span(target):
        a, e = (int(x) for x in target[len(lid) + 1:-1].split(":"))
        return text[a:e]

    edits = {(e.kind, span(e.target), e.text) for e in t.edits if e.target.startswith(f"{lid}[")}
    assert edits == {("corrected", "teh", "the"), ("expanded", "Dr.", "Doctor"), ("regularized", "vvhich", "which"),
                     ("joined", "divid-", "divided")}
    assert [(e.target, e.text) for e in t.edits if e.target.startswith(lines[1].id)] == [
        (f"{lines[1].id}[0:2]", "divided")]
    status = {c.value: c.target for c in t.classifications if c.scheme == "status"}
    assert span(status["illegible"]) == "dim"
    gap = status["gap"]
    a, e = (int(x) for x in gap[len(lid) + 1:-1].split(":"))
    assert a == e and text[:a].endswith("letters ")
    languages = {span(c.target): c.value for c in t.classifications if c.scheme == "language" and c.target}
    assert languages == {"مرحبا بكم": "ar", "λόγος": "grc"} and t.language("") == "en"
    fmt = lines[0].reading.formatting[0]
    assert fmt.italic and fmt.bold and text[fmt.charspan[0]:fmt.charspan[1]] == "set"


def test_a_page_in_german_is_classified_once():
    doc = f"""<TEI {TEI} xml:lang="de"><text><body><div><p>Ein Absatz mit <foreign xml:lang="la">Latein</foreign>.</p>
    <p xml:lang="en">An English one.</p><p xml:lang="de">Noch einer.</p></div></body></text></TEI>"""
    t = from_tei(doc)
    language = [(c.target, c.value) for c in t.classifications if c.scheme == "language"]
    assert language == [("", "de"), ("paragraph_1", "en"), ("paragraph_0_l0[15:21]", "la")]
    assert t.language("paragraph_2_l0") == "de" and t.language("paragraph_1_l0") == "en"


def test_a_diplomatic_line_in_another_language_and_no_namespace():
    doc = """<teiCorpus><TEI xml:lang="de"><sourceDoc><surface><zone type="paragraph">
    <line>Erste Zeile</line><line xml:lang="el">δεύτερη γραμμή</line></zone></surface></sourceDoc></TEI></teiCorpus>"""
    t = from_tei(doc)
    assert [(c.target, c.value) for c in t.classifications if c.scheme == "language"] == [
        ("", "de"), ("paragraph_0_l1", "el")]
    assert not hasattr(t.source, "tei__namespace") or t.source.tei__namespace is None


# ------------------------------------------------------------------------------------------- the importer


def test_auto_import_tells_tei_apart():
    assert sniff(FACSIMILE.encode()) == "tei" and sniff(DIPLOMATIC.encode()) == "tei"
    assert sniff(f"<?xml version='1.0'?><!-- c --><tei:teiCorpus xmlns:tei='http://www.tei-c.org/ns/1.0'/>"
                 .encode()) == "tei"
    assert sniff(b"<TEI><text/></TEI>") == "text"               # TEI's namespace is what tells it apart
    t = AutoImporter()(SourceDocument(data=DIPLOMATIC))
    assert t.source.format == "tei" and t.order().regions[0] == "rh"
    rule = [a for a in t.annotators if a.kind == "rule"]
    assert [a.engine for a in rule] == ["import.auto.v1"]


def test_the_importer_reads_the_page_its_option_names_and_fits_the_image():
    t = TeiImporter(page="pb2", ground_truth=False)(SourceDocument(data=FACSIMILE, image_width=1200,
                                                                   image_height=1800))
    assert t.source.kind == "converted" and [ln.reading.text for ln in t.lines] == ["Page two."]
    assert t.regions[0].box == [20.0, 40.0, 1160.0, 80.0] and t.source.image_width == 1200
    assert "page" in TeiImporter.Options.model_json_schema()["properties"]


def test_unknown_elements_never_fail_and_keep_their_text():
    doc = f"""<TEI {TEI}><text><body><p>One <foo:bar xmlns:foo="https://example.org/">two</foo:bar>
    <weird><deeper>three</deeper></weird></p><mystery>four</mystery></body></text></TEI>"""
    t = from_tei(doc)
    assert [ln.reading.text for ln in t.lines] == ["One two three", "four"]


# ------------------------------------------------------------------------------------------- scoring


def test_a_tei_page_scored_against_itself():
    t = from_tei(INLINE)
    full, body = rendered(t, "full"), rendered(t, "body")
    assert "�" * 3 + " letters" in full and "teh" in full     # unclear text illegible, corrections not applied
    assert "ON TESTS" in full and "ON TESTS" not in body            # furniture in full only
    out = score_page(t, t)
    assert out["rows"] and all(r["s"] == r["d"] == r["i"] == 0 for r in out["rows"])
    assert {"paragraph", "header", "page_number", "catch_word", "signature_mark"} <= set(out["roles"])
    d = from_tei(DIPLOMATIC)
    scored = score_page(d, d)
    assert {"header", "page_number", "paragraph", "footnote"} <= set(scored["roles"])
    assert all(r["s"] == r["d"] == r["i"] == 0 for r in scored["rows"])
