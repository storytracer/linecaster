"""OmniDocBench's formats: a linecaster ground truth as its ground-truth JSON, a run's page as its Markdown prediction,
and the export folder its own evaluation reads (which runs in its own environment, never in linecaster)."""
from __future__ import annotations

import json

from linecaster.data import Annotator, Source, Transcription
from linecaster.data.transcription import Cell, Formula, Table
from linecaster.formats.omnidocbench import export, prediction_markdown, table_html, truth_page


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
    """A data table (``linecaster.scoring.tables``): a heading over two columns, then two rows of text."""
    cells = [Cell(start_row=0, end_row=1, start_col=0, end_col=2, text="Officers & offices", column_header=True),
             Cell(start_row=1, end_row=2, start_col=0, end_col=1, text="Sarah C. Mink"),
             Cell(start_row=1, end_row=2, start_col=1, end_col=2, text="President"),
             Cell(start_row=2, end_row=3, start_col=0, end_col=1, text="Emma R. Wallace"),
             Cell(start_row=2, end_row=3, start_col=1, end_col=2, text="Secretary")]
    return Table(annotator=0, target="r2", num_rows=3, num_cols=2, cells=cells)


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
    assert table_html(_grid()) == ('<table><tr><th colspan="2">Officers &amp; offices</th></tr>'
                                   "<tr><td>Sarah C. Mink</td><td>President</td></tr>"
                                   "<tr><td>Emma R. Wallace</td><td>Secretary</td></tr></table>")


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


def test_an_export_is_the_truth_json_one_prediction_per_page_and_what_made_them(tmp_path):
    import yaml

    from linecaster.data import Page

    def row(pid, name, t):
        page = Page(page_id=pid, item_id="item", transcriptions={name: t})
        return {"schema": "linecaster.page/6", "id": pid, "text": t.text, "page": page.record()}

    gt = {f"p{i}": _page([("paragraph", [f"page {i} cafe\u0301"])]) for i in range(3)}
    truth = {pid: row(pid, "ground_truth", t) for pid, t in gt.items()}
    run = {pid: row(pid, "ocr_new", gt[pid]) for pid in ("p0", "p1")}               # p2: the run lacks it
    run["p1"]["errors"] = [{"error": "timeout"}]                                     # p1: failed, an empty prediction
    counts = export(tmp_path / "s", truth, run, strategy="nfc")
    assert counts == {"pages": 3, "missing": 1, "failed": 1}
    pages = json.loads((tmp_path / "s/truth.json").read_text())
    assert [p["page_info"]["image_path"] for p in pages] == ["p0.png", "p1.png", "p2.png"]
    assert pages[0]["page_info"]["page_attribute"] == {"tables": "no", "formulas": "no"}
    assert pages[0]["layout_dets"][0]["text"] == "page 0 caf\u00e9"                 # the strategy on both sides
    assert [(tmp_path / f"s/predictions/p{i}.md").read_text() for i in range(3)] == ["page 0 caf\u00e9", "", ""]
    record = yaml.safe_load((tmp_path / "s/export.yaml").read_text())
    assert (record["strategy"], record["tables"], record["counts"]) == ("nfc", "data", counts)
    assert "pdf_validation.py" in (tmp_path / "s/README.md").read_text()


def test_only_data_tables_are_tables_on_both_sides_the_rest_is_their_text():
    from linecaster.formats.omnidocbench import table_text

    t = _page([("table", ["x"]), ("table", ["y"])])
    t.tables.append(Table(**{**_grid().model_dump(), "target": "r0"}))
    layout = Table(annotator=0, target="r1", num_rows=1, num_cols=2, cells=[
        Cell(start_row=0, end_row=1, start_col=0, end_col=1, text="Executive Mansion,"),
        Cell(start_row=0, end_row=1, start_col=1, end_col=2, text="}")])
    t.tables.append(layout)
    got = [(d["category_type"], d.get("html") or d.get("text")) for d in truth_page("p", t)["layout_dets"]]
    assert got == [("table", table_html(_grid())), ("text_block", "Executive Mansion, }")]
    assert [d["category_type"] for d in truth_page("p", t, tables="all")["layout_dets"]] == ["table", "table"]
    md = prediction_markdown(t)                                       # the run's tables by the same rule
    assert md == table_html(_grid()) + "\n\nExecutive Mansion, }"
    assert prediction_markdown(t, tables="all").count("<table>") == 2
    assert table_text(_grid()) == "Officers & offices\nSarah C. Mink President\nEmma R. Wallace Secretary"


def test_linecaster_export_omnidocbench_reads_page_records_and_writes_the_folder(tmp_path, capsys):
    from linecaster.cli import main
    from linecaster.data import Page

    def write(folder, name, ts):
        folder.mkdir()
        lines = [json.dumps({"schema": "linecaster.page/6", "id": pid, "text": t.text,
                             "page": Page(page_id=pid, item_id="item", transcriptions={name: t}).record()})
                 for pid, t in ts.items()]
        (folder / "00000.jsonl").write_text("\n".join(lines) + "\n")

    gt = {f"p{i}": _page([("paragraph", [f"page {i}"])]) for i in range(2)}
    write(tmp_path / "truth", "ground_truth", gt)
    write(tmp_path / "run", "ocr_new", {"p0": gt["p0"]})
    main(["export", "omnidocbench", str(tmp_path / "out"), "--truth", str(tmp_path / "truth"),
          "--pages", str(tmp_path / "run")])
    assert "pages 2, missing 1, failed 0" in capsys.readouterr().out
    assert sorted(p.name for p in (tmp_path / "out/predictions").iterdir()) == ["p0.md", "p1.md"]
