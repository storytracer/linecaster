"""Two ground truths of one page from two traditions: a TEI diplomatic page and an IIIF annotation page of the same
Greek text, told apart and imported by auto-import and scored against each other: what is printed is compared (the
TEI's abbreviation, not its expansion), and its unclear reading is an illegible span, not counted."""
from __future__ import annotations

import json

from linecaster.data import SourceFile
from linecaster.engines.importers import AutoImporter
from linecaster.evaluation import score_page

TEI = """<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:lang="grc"><teiHeader/>
<sourceDoc><surface ulx="0" uly="0" lrx="1000" lry="600">
 <zone type="paragraph" ulx="100" uly="100" lrx="900" lry="300">
  <line ulx="100" uly="100" lrx="900" lry="140">Ἐν ἀρχῇ ἦν ὁ λόγος,</line>
  <line ulx="100" uly="150" lrx="900" lry="190">καὶ ὁ λόγος ἦν <choice><abbr>π.</abbr><expan>πρὸς</expan></choice> τὸν θεόν.</line>
  <line ulx="100" uly="200" lrx="900" lry="240">οὗτος ἦν ἐν <unclear>ἀρχῇ</unclear>.</line>
 </zone></surface></sourceDoc></TEI>"""

CANVAS = "https://example.org/iiif/canvas/1"


def _iiif() -> str:
    def line(n, text, y):
        return {"id": f"https://example.org/anno/{n}", "type": "Annotation", "motivation": "supplementing",
                "textGranularity": "line", "body": {"type": "TextualBody", "value": text, "language": "grc"},
                "target": f"{CANVAS}#xywh=100,{y},800,40"}

    return json.dumps({"id": "https://example.org/anno", "type": "AnnotationPage", "items": [
        {"id": "https://example.org/anno/r", "type": "Annotation", "motivation": "classifying",
         "body": {"type": "TextualBody", "value": "paragraph"}, "target": f"{CANVAS}#xywh=100,100,800,200"},
        line(0, "Ἐν ἀρχῇ ἦν ὁ λόγος,", 100), line(1, "καὶ ὁ λόγος ἦν πρὸς τὸν θεόν.", 150),
        line(2, "οὗτος ἦν ἐν ἀρχῇ.", 200)]}, ensure_ascii=False)


def test_a_tei_page_and_an_iiif_page_of_one_text_score_against_each_other():
    tei = AutoImporter()(SourceFile(data=TEI))
    assert tei.source.format == "tei" and tei.language("") == "grc"
    assert [(e.kind, e.text) for e in tei.edits] == [("expanded", "πρὸς")]

    def score(iiif_text: str) -> dict:
        iiif = AutoImporter()(SourceFile(data=iiif_text))
        assert (iiif.source.format, iiif.language("")) == ("iiif", "grc")
        row = score_page(tei, iiif, lanes=("diplomatic",))["rows"][0]
        return {k: row[k] for k in ("s", "d", "i", "words_true", "words_both")}

    # what is printed is compared: the TEI's abbreviation, not its expansion; its unclear word is not counted
    assert score(_iiif().replace("πρὸς", "π.")) == {"s": 0, "d": 0, "i": 0, "words_true": 15, "words_both": 15}
    assert score(_iiif().replace("πρὸς", "π.").replace("ἐν ἀρχῇ", "ἐν ἀρχή"))["s"] == 0
    assert score(_iiif()) == {"s": 1, "d": 0, "i": 2, "words_true": 15, "words_both": 14}
