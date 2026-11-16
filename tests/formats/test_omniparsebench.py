"""Omni Parse Bench: a run's page as its prediction file, the writer, and its own grading of a folder of them
(``pipelines/omniparsebench.py``), on a small dataset made here."""
from __future__ import annotations

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from datatrove.data import Document

from linecaster.data import Annotator, Page, Source, Transcription
from linecaster.data.transcription import Cell, Table

pytest.importorskip("omni_parse_bench")

from linecaster.blocks.writers import OmniParseBenchPredictionWriter  # noqa: E402
from linecaster.formats.omniparsebench import page_html, prediction  # noqa: E402
from linecaster.pipelines.omniparsebench import grade  # noqa: E402


def _page(blocks: list[tuple[str, list[str]]], table: bool = False) -> Transcription:
    t = Transcription(source=Source(image_width=1000, image_height=1400))
    a = t.add_annotator(Annotator(step="layout", name="test"))
    lines = []
    for k, (role, texts) in enumerate(blocks):
        t.add_region(a, f"r{k}", [0, 100 * k, 1000, 90], role=role)
        for j, s in enumerate(texts):
            lines.append(t.add_line(a, f"r{k}_l{j}", region=f"r{k}", text=s).id)
    t.add_order(a, [r.id for r in t.regions], lines)
    if table:
        cells = [Cell(start_row=r, end_row=r + 1, start_col=c, end_col=c + 1, text=s, column_header=r == 0)
                 for r, row in enumerate([["Year", "Members"], ["1862", "90,000"], ["1881", "165,000"]])
                 for c, s in enumerate(row)]
        t.tables.append(Table(annotator=0, target=f"r{len(blocks) - 1}", num_rows=3, num_cols=2, cells=cells))
    return t


def test_a_page_is_its_html_in_reading_order_with_tables_as_html():
    t = _page([("heading", ["THE HISTORY"]), ("paragraph", ["The kinetic energy is", "here regarded."]),
               ("table", ["x"])], table=True)
    html = page_html(t)
    assert html.index("THE HISTORY") < html.index("The kinetic energy is") < html.index("<table")
    assert "<td>90,000</td>" in html.replace(" ", "")
    assert prediction(t) == {"pages": [{"html": html}]}
    assert prediction(None) == {"pages": [{"html": ""}]}


def _dataset(root, pages: dict[str, list[dict]]):
    (root / "gold").mkdir(parents=True)
    rows = []
    for pid, tests in pages.items():
        (root / "gold" / f"{pid}.json").write_text(json.dumps({"tests": tests}))
        rows.append({"page_id": pid, "document": pid.rsplit("_", 1)[0], "suite": "test", "doc_path": "pages/x.png",
                     "gt_path": f"gold/{pid}.json", "outputs": ["html"]})
    (root / "pages").mkdir()
    (root / "pages" / "x.png").write_bytes(b"")
    pq.write_table(pa.Table.from_pylist(rows), root / "manifest.parquet")


def _present(pid, k, text):
    return {"id": f"{pid}_p{k}", "test_type": "present", "output_type": "html", "derivation": "authored",
            "tags": ["eng"], "args": {"content": {"text": text, "max_diffs": 0}}, "settings": {}}


def test_the_writer_writes_predictions_and_failures_that_omni_parse_bench_grades(tmp_path):
    good = _page([("paragraph", ["The kinetic energy is here regarded as a function."])])
    docs = [Document(text="", id="a_0001", metadata={"page": Page(page_id="a_0001", item_id="a",
                                                                  transcriptions={"ocr_new": good}).model_dump()}),
            Document(text="", id="a_0002", metadata={"errors": [{"type": "Timeout", "error": "no answer"}]})]
    out = tmp_path / "run"
    list(OmniParseBenchPredictionWriter(str(out)).run(iter(docs)))
    assert json.loads((out / "records" / "a_0002.json").read_text())["error"]["type"] == "Timeout"
    _dataset(tmp_path / "ds", {"a_0001": [_present("a_0001", 0, "the kinetic energy is here regarded"),
                                          _present("a_0001", 1, "not on the page at all")],
                               "a_0002": [_present("a_0002", 0, "anything")]})
    one = grade(str(out), str(tmp_path / "ds"), workers=1)["summary"]
    two = grade(str(out), str(tmp_path / "ds"), workers=2)["summary"]
    assert one["rows"] == 2 and one["failed"]["system"] == 1
    assert one["score"] == two["score"] and one["families"] == two["families"]       # the pool changes nothing
    assert (out / "unit_tests" / "summary.json").is_file() and (out / "omniparsebench.yaml").is_file()
