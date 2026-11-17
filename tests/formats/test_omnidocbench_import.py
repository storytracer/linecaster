"""OmniDocBench's ground truth read into page records (``linecaster.formats.omnidocbench.from_omnidocbench``,
``import.omnidocbench.v1``): a ground truth written as OmniDocBench's entry and read back keeps its texts, roles (as far
as the categories tell them apart), order, tables and formulas; an entry's spans give lines with boxes, divided words
and inline formulas; a real entry of OmniDocBench's demo data, where a checkout has it (its data stays there)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from linecaster.data import Annotator, Source, SourceFile, Transcription
from linecaster.data.transcription import Cell, Formula, Table
from linecaster.formats.omnidocbench import (
    entries,
    from_omnidocbench,
    page_id,
    truth_page,
)
from linecaster.evaluation.render import text

DEMO = Path.home() / "dev/OmniDocBench/demo_data/omnidocbench_demo/OmniDocBench_demo.json"


def _truth() -> Transcription:
    t = Transcription(source=Source(image_width=1000, image_height=1400))
    a = t.add_annotator(Annotator(kind="human", step="transcription", name="test"))
    blocks = [("header", ["THE HISTORY"]), ("heading", ["CHAPTER I."]),
              ("paragraph", ["the forces", "where $n$ is the count"]), ("table", []), ("formula", []),
              ("caption", ["Fig. 1. A cricket."]), ("footnote", ["A note."]), ("page_number", ["12"])]
    lines = []
    for k, (role, texts) in enumerate(blocks):
        t.add_region(a, f"r{k}", [0, 100 * k, 1000, 90], role=role)
        for j, s in enumerate(texts):
            lines.append(t.add_line(a, f"r{k}_l{j}", region=f"r{k}", text=s).id)
    t.add_order(a, [r.id for r in t.regions], lines)
    t.formulas += [Formula(annotator=a, target="r2_l1[6:9]", latex="n"),
                   Formula(annotator=a, target="r4", latex="E = mc^2")]
    t.tables.append(Table(annotator=a, target="r3", num_rows=3, num_cols=2, cells=[
        Cell(start_row=0, end_row=1, start_col=0, end_col=2, text="Officers", column_header=True),
        Cell(start_row=1, end_row=2, start_col=0, end_col=1, text="Sarah C. Mink"),
        Cell(start_row=1, end_row=2, start_col=1, end_col=2, text="President"),
        Cell(start_row=2, end_row=3, start_col=0, end_col=1, text="Emma R. Wallace"),
        Cell(start_row=2, end_row=3, start_col=1, end_col=2, text="Secretary")]))
    return t


def test_a_ground_truth_written_as_an_entry_reads_back():
    gt = _truth()
    entry = truth_page("p_0001", gt, attributes={"language": "english", "layout": "single_column"})
    back = from_omnidocbench(json.loads(json.dumps(entry)))
    assert text(back, "full") == text(gt, "full") and text(back, "body") == text(gt, "body")
    roles = [back.role(r.id) for r in back.ordered_regions()]
    assert roles == ["header", "heading", "paragraph", "table", "formula", "caption", "footnote", "page_number"]
    assert [r.label for r in back.ordered_regions()][:3] == ["header", "title", "text_block"]
    (table,) = back.tables
    assert [(c.start_row, c.start_col, c.text, c.column_header) for c in table.cells] == [
        (c.start_row, c.start_col, c.text, c.column_header) for c in gt.tables[0].cells]
    assert sorted(f.latex for f in back.formulas) == ["E = mc^2", "n"]
    (inline,) = [f for f in back.formulas if "[" in f.target]
    line = back.line(inline.target.split("[")[0])
    assert back.text_of(line)[6:9] == "$n$"
    assert back.language("") == "en" and back.source.extensions == {"omnidocbench__language": "english",
                                                                    "omnidocbench__layout": "single_column",
                                                                    "omnidocbench__page_no": 0}
    assert (back.source.kind, back.source.format, back.source.record) == ("ground_truth", "omnidocbench",
                                                                          "p_0001.png")
    assert back.annotators[0].kind == "human" and from_omnidocbench(entry, ground_truth=False).annotators[0].kind == "file"


def _span(text, x, y, w=100, h=20, category="text_span", key="text"):
    return {"category_type": category, "poly": [x, y, x + w, y, x + w, y + h, x, y + h], key: text}


def test_spans_give_lines_with_boxes_divided_words_and_inline_formulas():
    entry = {"layout_dets": [
        {"category_type": "text_block", "poly": [10, 10, 500, 10, 500, 80, 10, 80], "ignore": False, "order": 1,
         "anno_id": 3, "text": "The eluant was concentrated by rotary evaporator to $ 1 ml $ under nitrogen.",
         "attribute": {"text_language": "text_english"},
         "line_with_spans": [_span("The eluant was concentrated by rotary evap-", 10, 10, 480),
                             _span("orator to", 10, 40, 80), _span("$ 1 ml $", 95, 41, 40, key="latex",
                                                                   category="equation_inline"),
                             _span("under nitrogen.", 140, 40, 200)]},
        {"category_type": "header", "poly": [10, 0, 200, 0, 200, 8, 10, 8], "ignore": False, "order": None,
         "anno_id": 0, "text": "J. Chromatogr.", "attribute": {"text_language": "text_simplified_chinese"}},
        {"category_type": "abandon", "poly": [10, 90, 200, 90, 200, 98, 10, 98], "ignore": False, "order": None,
         "anno_id": 1, "text": "Downloaded from example.org"},
        {"category_type": "equation_isolated", "poly": [10, 100, 300, 100, 300, 130, 10, 130], "ignore": True,
         "order": 2, "anno_id": 2, "latex": "$$\nx^2\n$$"},
        {"category_type": "figure_caption", "poly": [10, 140, 300, 140, 300, 160, 10, 160], "ignore": False,
         "order": 3, "anno_id": 4, "text": "Fig. 1"},
        {"category_type": "figure", "poly": [10, 170, 300, 170, 300, 400, 10, 400], "ignore": False, "order": 4,
         "anno_id": 5}],
        "page_info": {"page_no": 3, "height": 1400, "width": 1000, "image_path": "docs/paper_3.jpg",
                      "page_attribute": {"language": "en_ch_mixed", "data_source": "academic_literature",
                                         "special_issue": ["fuzzy_scan"]}},
        "extra": {"relation": [{"source_anno_id": 5, "target_anno_id": 4, "relation_type": "parent_son"},
                               {"source_anno_id": 3, "target_anno_id": 4, "relation_type": "other"}]}}
    t = from_omnidocbench(json.dumps(entry))
    l0, l1 = t.lines_of("r3")
    assert (t.text_of(l0), t.text_of(l1)) == ("The eluant was concentrated by rotary evap-",
                                              "orator to $ 1 ml $ under nitrogen.")
    assert l0.box == [10.0, 10.0, 480.0, 20.0] and l1.box == [10.0, 40.0, 330.0, 21.0]
    assert [(e.target, e.kind, e.text) for e in t.edits] == [("r3_l0[38:43]", "joined", "evaporator"),
                                                             ("r3_l1[0:6]", "joined", "evaporator")]
    (inline,) = [f for f in t.formulas if f.target.startswith("r3_l1")]
    assert t.text_of(l1)[slice(*map(int, inline.target[6:-1].split(":")))] == "$ 1 ml $" and inline.latex == "1 ml"
    assert t.formula("r2").latex == "x^2" and t.status("r2") == "suppressed" and t.status("r1") == "suppressed"
    assert t.order("regions").regions == ["r3", "r2", "r4", "r5"]                  # furniture and discards unordered
    assert [r.id for r in t.ordered_regions()][-2:] == ["r0", "r1"]
    assert t.language("") == "mul" and t.language("r0") == "zh-Hans" and t.language("r3") == "en"
    assert t.source.extensions["omnidocbench__special_issue"] == ["fuzzy_scan"]
    assert (t.source.record, t.source.image_width, t.source.image_height) == ("docs/paper_3.jpg", 1000, 1400)
    assert [(ln.kind, ln.source, ln.target) for ln in t.links] == [("caption_of", "r4", "r5")]
    assert t.extensions["omnidocbench__relation"] == [entry["extra"]["relation"][1]]
    assert t.region("r3").extensions == {"omnidocbench__anno_id": 3,
                                         "omnidocbench__attribute": {"text_language": "text_english"}}
    assert t.region("r5").polygon == [[10.0, 170.0], [300.0, 170.0], [300.0, 400.0], [10.0, 400.0]]
    assert t.role("r5") == "picture" and t.role("r1") == "other" and t.region("r1").label == "abandon"
    assert "Downloaded" not in text(t, "full") and "$x^2$" not in text(t, "full")
    assert page_id(entry) == "paper_3"


def test_the_importer_reads_an_entry_and_fits_it_to_the_page_image():
    from linecaster.engines.importers import OmniDocBenchImporter

    entry = truth_page("p1", _truth(), attributes={"language": "simplified_chinese"})
    entry["layout_dets"][0]["poly"] = [0, 0, 500, 0, 500, 50, 0, 50]
    t = OmniDocBenchImporter()(SourceFile(data=json.dumps(entry), image_width=500, image_height=700,
                                              record="row-1"))
    assert t.source.kind == "ground_truth" and t.language("") == "zh-Hans"
    assert t.regions[0].box == [0.0, 0.0, 250.0, 25.0]                             # 1000 x 1400 onto 500 x 700
    assert [a.kind for a in t.annotators] == ["human", "rule"]


def test_entries_split_the_json_list_into_pages(tmp_path):
    path = tmp_path / "truth.json"
    path.write_text(json.dumps([truth_page("a_1", _truth()), truth_page("b_2", _truth())]))
    assert [pid for pid, _ in entries(path)] == ["a_1", "b_2"]
    with pytest.raises(ValueError, match="page id"):
        page_id({"page_info": {"image_path": "x#1.png"}})


@pytest.mark.skipif(not DEMO.is_file(), reason="OmniDocBench's demo data is not checked out here")
def test_a_real_entry_of_omnidocbench_s_demo_data():
    from linecaster.evaluation.tables import table_kind

    pages = dict(entries(DEMO))
    for pid, entry in pages.items():
        t = from_omnidocbench(entry)
        assert len(t.regions) == len(entry["layout_dets"])
        ordered = [d for d in entry["layout_dets"] if d.get("order") is not None]
        assert len(t.order("regions").regions) == len(ordered)
        texts = {f"r{d['anno_id']}": d["text"] for d in entry["layout_dets"] if d.get("text")
                 and d["category_type"] != "table"}
        for rid, s in texts.items():                                # the block's text, line by line
            got = "".join(t.text_of(ln) for ln in t.lines_of(rid))           # a division mark kept, spaces cut
            assert "".join(got.split()).replace("-", "") == "".join(s.split()).replace("-", ""), rid
        for tb in t.tables:
            assert table_kind(tb) in ("data", "contents", "layout")
    assert {from_omnidocbench(e).language("") for e in pages.values()} <= {"en", "zh-Hans", "mul"}
