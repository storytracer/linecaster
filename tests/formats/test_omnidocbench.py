"""OmniDocBench's formats: a linecaster ground truth as its ground-truth JSON, a run's page as its Markdown prediction,
and the harness's config and summary (``linecaster.scoring.harness``; the harness itself runs in its own environment,
not in the tests)."""
from __future__ import annotations

import json

from linecaster.data import Annotator, Source, Transcription
from linecaster.data.transcription import Cell, Formula, Table
from linecaster.formats.omnidocbench import prediction_markdown, table_html, truth_page
from linecaster.scoring.harness import config, export, summarize


def _page(blocks: list[tuple[str, list[str]]]) -> Transcription:
    t = Transcription(source=Source(image_width=1000, image_height=1400))
    a = t.add_annotator(Annotator(step="layout", name="test"))
    lines = []
    for k, (role, texts) in enumerate(blocks):
        t.add_region(a, f"r{k}", [0, 100 * k, 1000, 90], role=role)
        for j, s in enumerate(texts):
            lines.append(t.add_line(a, f"r{k}_l{j}", region=f"r{k}", text=s).id)
    t.add_order(a, [r.id for r in t.regions], lines)
    return t


def _grid() -> Table:
    cells = [Cell(start_row=0, end_row=1, start_col=0, end_col=2, text="Chapter & page", column_header=True),
             Cell(start_row=1, end_row=2, start_col=0, end_col=1, text="I. Grasshopper"),
             Cell(start_row=1, end_row=2, start_col=1, end_col=2, text="1")]
    return Table(annotator=0, target="r2", num_rows=2, num_cols=2, cells=cells)


def test_a_ground_truth_page_is_omnidocbench_elements_in_reading_order():
    t = _page([("header", ["THE HISTORY"]), ("paragraph", ["the forces", "$F_{1}dq_{1}$ (1)", "where $n$ is"]),
               ("table", ["x"]), ("footnote", ["A note."]), ("page_number", ["12"])])
    t.formulas += [Formula(annotator=0, target="r1_l1[0:13]", latex="F_{1}dq_{1}"),       # fills its line: display
                   Formula(annotator=0, target="r1_l2[6:9]", latex="n")]                   # inline: stays in the text
    t.tables.append(_grid())
    page = truth_page("p_0001", t, attributes={"tables": "yes"})
    got = [(d["category_type"], d.get("text") or d.get("latex") or d.get("html")) for d in page["layout_dets"]]
    assert got == [("header", "THE HISTORY"), ("text_block", "the forces"), ("equation_isolated", "$$F_{1}dq_{1}$$"),
                   ("text_block", "where $n$ is"), ("table", table_html(_grid())), ("page_footnote", "A note."),
                   ("page_number", "12")]
    assert [d["order"] for d in page["layout_dets"]] == list(range(1, 8))
    assert all(d["ignore"] is False and "poly" not in d for d in page["layout_dets"])
    assert page["page_info"]["image_path"] == "p_0001.png" and page["page_info"]["page_attribute"] == {"tables": "yes"}


def test_a_table_is_html_with_its_spans_and_headers():
    assert table_html(_grid()) == ('<table><tr><th colspan="2">Chapter &amp; page</th></tr>'
                                   "<tr><td>I. Grasshopper</td><td>1</td></tr></table>")


def test_a_prediction_is_markdown_blocks_and_a_completion_stays_as_written():
    t = _page([("heading", ["CHAPTER I."]), ("paragraph", ["We shall use", "Hamilton's form"]), ("formula", ["F1 d"]),
               ("table", ["<table>"]), ("picture", ["a drawing of a cricket"])])
    t.classify(0, "r0", "heading_level", "2")
    t.formulas.append(Formula(annotator=0, target="r2", latex="F_1 dq_1"))
    t.tables.append(Table(**{**_grid().model_dump(), "target": "r3"}))
    md = prediction_markdown(t)
    assert md == ("## CHAPTER I.\n\nWe shall use\nHamilton's form\n\n$$\nF_1 dq_1\n$$\n\n" + table_html(_grid()))
    plain = Transcription(source=Source())
    a = plain.add_annotator(Annotator(step="recognition", name="vlm"))
    for i, s in enumerate(["# CONTENTS", "", "<table><tr><td>PREFACE</td></tr></table>"]):
        plain.add_line(a, f"l{i}", text=s)
    assert prediction_markdown(plain) == "# CONTENTS\n\n<table><tr><td>PREFACE</td></tr></table>"
    assert prediction_markdown(None) == ""


def test_export_writes_the_truth_json_and_one_prediction_per_page(tmp_path):
    from linecaster.data import Page

    def records(folder, name, ts):
        folder.mkdir(parents=True)
        with open(folder / "00000.jsonl", "w") as f:
            for pid, t in ts.items():
                page = Page(page_id=pid, item_id="item", transcriptions={name: t})
                f.write(json.dumps({"schema": "linecaster.page/5", "id": pid, "text": t.text, "page": page.record()})
                        + "\n")

    gt = {f"p{i}": _page([("paragraph", [f"page {i}"])]) for i in range(3)}
    records(tmp_path / "gt", "ground_truth", gt)
    records(tmp_path / "run", "ocr_new", {"p0": gt["p0"], "p1": gt["p1"]})           # p2: the run lacks it
    counts = export(tmp_path / "h", str(tmp_path / "run"), str(tmp_path / "gt"), workers=1)
    assert counts == {"pages": 3, "predictions": 2, "missing": 1}
    truth = json.loads((tmp_path / "h/truth.json").read_text())
    assert [p["page_info"]["image_path"] for p in truth] == ["p0.png", "p1.png", "p2.png"]
    assert truth[0]["page_info"]["page_attribute"] == {"tables": "no", "formulas": "no", "table-heavy": "no"}
    assert (tmp_path / "h/predictions/p1.md").read_text() == "page 1"
    assert (tmp_path / "h/predictions/p2.md").read_text() == ""


def test_the_config_names_every_module_and_cdm_only_when_asked(tmp_path):
    import yaml

    cfg = yaml.safe_load(config(tmp_path, cdm=False, workers=4).read_text())["end2end_eval"]
    assert cfg["metrics"]["display_formula"]["metric"] == ["Edit_dist"]
    assert cfg["metrics"]["table"]["metric"] == ["TEDS", "Edit_dist"] and cfg["dataset"]["match_method"] == "quick_match"
    assert cfg["dataset"]["prediction"]["data_path"] == str(tmp_path / "predictions")
    assert "CDM" in yaml.safe_load(config(tmp_path, cdm=True, workers=4).read_text())[
        "end2end_eval"]["metrics"]["display_formula"]["metric"]


def test_the_summary_reads_the_harness_result():
    result = {"text_block": {"all": {"Edit_dist": {"ALL_page_avg": 0.1}},
                             "page": {"Edit_dist": {"ALL": 0.1, "tables: yes": 0.3}}},
              "table": {"all": {"TEDS": {"all": 0.8}, "TEDS_structure_only": {"all": 0.9},
                                "Edit_dist": {"ALL_page_avg": 0.2}}},
              "display_formula": {"all": {"Edit_dist": {"ALL_page_avg": 0.25}}},
              "reading_order": {"all": {"Edit_dist": {"ALL_page_avg": 0.05}}}}
    s = summarize(result)
    assert (s["text_edit"], s["table_teds"], s["table_teds_s"], s["formula_edit"]) == (0.1, 0.8, 0.9, 0.25)
    assert "formula_cdm" not in s and s["groups"] == {"tables: yes": {"text_edit": 0.3}}
