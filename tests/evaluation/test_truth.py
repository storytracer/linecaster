"""A ground truth checked (``linecaster truth check``), turned into a benchmark definition (``linecaster benchmark
init``) and published as a Hub dataset (``linecaster truth publish``), on page records written for the tests."""
from __future__ import annotations

import io
import json

import pytest
import yaml

from linecaster.data import Annotator, Page, PageImage, Source, Transcription
from linecaster.data.transcription import Cell, Formula, Link, Table
from linecaster.evaluation.truth import (
    check,
    check_page,
    page_values,
    script_note,
    summarize,
    supports,
)


def _truth(lines: list[str], language: str | None = "en", boxes: bool = True, order: bool = True,
           conventions: bool = False) -> Transcription:
    t = Transcription(source=Source(kind="ground_truth", image_width=1000, image_height=1400,
                                    dataset="example/truth@r1"))
    a = t.add_annotator(Annotator(kind="human", step="transcription", name="test"))
    rule = t.add_annotator(Annotator(kind="rule", step="import", name="import.page.v1", preset="page-xml-import"))
    if conventions:
        t.annotators[rule].conventions, t.annotators[rule].conventions_sha256 = "html>example", "sha256:abc"
        t.annotators[rule].measurements["unmapped"] = {"div.x": 2}
    t.add_region(a, "r0", [0, 0, 1000, 100] if boxes else None, role="header")
    t.add_region(a, "r1", [0, 100, 1000, 1200] if boxes else None, role="paragraph")
    t.add_line(a, "r0_l0", [0, 0, 500, 40] if boxes else None, region="r0", text="THE HISTORY")
    for j, s in enumerate(lines):
        t.add_line(a, f"r1_l{j}", [0, 100 + 50 * j, 900, 40] if boxes else None, region="r1", text=s)
    if order:
        t.add_order(a, ["r0", "r1"], [ln.id for ln in t.lines])
    if language:
        t.classify(a, "", "language", language)
    return t


def _row(pid: str, t: Transcription, item: str = "item", image: str | None = None) -> str:
    page = Page(page_id=pid, item_id=item, transcriptions={"ground_truth": t},
                image=PageImage(uri=image, width=1000, height=1400) if image else None)
    return json.dumps({"schema": "linecaster.page/6", "id": pid, "text": t.text, "page": page.record()},
                      ensure_ascii=False)


def _write(folder, rows: list[str]) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "00000.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(folder)


def test_a_page_s_report():
    t = _truth(["the forces", "", "of nature"], conventions=True)
    t.lines[1].box = [990, 100, 50, 40]                                        # beyond the image's right edge
    t.classify(0, "r1_l0[4:7]", "status", "illegible")
    t.classify(0, "r1", "script", "Latn")
    t.tables.append(Table(annotator=0, target="r1", num_rows=2, num_cols=2, cells=[
        Cell(start_row=r, end_row=r + 1, start_col=c, end_col=c + 1, text=f"{r}{c}") for r in range(2)
        for c in range(2)]))
    t.formulas.append(Formula(annotator=0, target="r1_l2[0:2]", latex="x"))
    t.links.append(Link(annotator=0, kind="continues", source="r1", target="p0#r1"))
    got = check_page(Page(page_id="p1", item_id="i", transcriptions={"ground_truth": t}))
    assert (got["lines"], got["lines_with_text"], got["empty_lines"]) == (4, 3, 1)
    assert got["boxes_outside"] == 1 and got["image_size"] == [1000, 1400]
    assert (got["reading_order"], got["unranked_regions"], got["unranked_lines"]) == ("complete", 0, 0)
    assert got["conventions"] == [{"conventions": "html>example", "sha256": "sha256:abc"}]
    assert got["unmapped"] == {"div.x": 2}
    assert got["illegible_characters"] == 3 and got["characters"] == len("THE HISTORYthe forcesof nature")
    assert (got["language"], got["script"], got["scripts"]) == ("en", None, ["Latn"])
    assert got["roles"] == {"header": 1, "paragraph": 1} and got["statuses"] == {"illegible": 1}
    assert got["tables"] == 1 and got["table_kinds"] == {"data": 1}
    assert got["formulas"] == {"regions": 0, "inline": 1} and got["continuations"] == 1
    assert check_page(Page(page_id="p2"))["missing"] is True


def test_reading_orders_none_partial_complete():
    none = check_page(Page(page_id="a", transcriptions={"ground_truth": _truth(["x"], order=False)}))
    assert none["reading_order"] == "none"
    partial = _truth(["x", "y"])
    partial.orders[0].regions.remove("r0")
    got = check_page(Page(page_id="b", transcriptions={"ground_truth": partial}))
    assert (got["reading_order"], got["unranked_regions"]) == ("partial", 1)
    lines_only = Transcription()
    a = lines_only.add_annotator(Annotator(kind="human", step="transcription", name="t"))
    for i in range(3):
        lines_only.add_line(a, f"l{i}", text=str(i))
    lines_only.add_order(a, lines=["l0", "l1", "l2"])
    assert check_page(Page(page_id="c", transcriptions={"ground_truth": lines_only}))["reading_order"] == "complete"


def test_the_totals_duplicates_and_what_it_supports(tmp_path):
    folder = _write(tmp_path / "truth", [_row("p1", _truth(["one"])), _row("p2", _truth(["one"], language=None)),
                                         _row("p3", _truth(["two"], language="he", boxes=False), item="other")])
    report = check(folder)
    tot = report["total"]
    assert (tot["pages"], tot["items"], tot["lines"]) == (3, 2, 6)
    assert tot["languages"] == {"en": 1, "he": 1} and tot["pages_without_language"] == 1
    assert tot["duplicates"] == [["p1", "p2"]]
    assert tot["reading_order"] == {"complete": 3}
    s = supports(report["pages"])
    assert s == {"roles": ["header", "paragraph"], "boxes": False, "reading_order": True, "notes": False,
                 "continuations": False}
    assert check(folder, ids={"p3", "p9"})["total"]["missing"] == 1
    assert summarize([]) ["pages"] == 0


def test_page_values_for_strata():
    t = _truth(["x"])
    t.source.example__collection = "letters"
    page = Page(page_id="p", metadata={"example__century": "18"}, transcriptions={"ground_truth": t})
    assert page_values(page, "language") == "en"
    assert page_values(page, "metadata.example__century") == "18"
    assert page_values(page, "source.example__collection") == "letters"
    assert page_values(page, "source.dataset") == "example/truth@r1"
    assert page_values(page, "script") is None and page_values(Page(page_id="q"), "language") is None


def test_linecaster_truth_check_prints_the_report_and_writes_json(tmp_path, capsys):
    from linecaster.cli import main

    folder = _write(tmp_path / "truth", [_row("p1", _truth(["one"], conventions=True)),
                                         _row("p2", _truth(["two"], order=False))])
    (tmp_path / "ids").write_text("p1\np2\n")
    main(["truth", "check", folder, "--ids", str(tmp_path / "ids"), "--json", str(tmp_path / "check.json")])
    out = capsys.readouterr().out
    assert "pages 2 (items 1)" in out and "reading order: complete 1, none 1" in out
    assert "conventions html>example (sha256:abc): 1 pages" in out and "pages without a reading order (1): p2" in out
    report = json.loads((tmp_path / "check.json").read_text())
    assert report["schema"] == "linecaster.truth-check/1" and len(report["pages"]) == 2


def test_linecaster_benchmark_init_writes_a_valid_definition(tmp_path, capsys):
    from linecaster.cli import main
    from linecaster.data.sample import listing_sha256
    from linecaster.evaluation.benchmark import read_benchmark

    rows = [_row(f"b{i}_{j}", _truth([f"page {i} {j}"], language=("zh-Hans" if i % 2 else "en")), item=f"b{i}")
            for i in range(8) for j in range(3)]
    folder = _write(tmp_path / "truth", rows)
    out = tmp_path / "bench.yaml"
    main(["benchmark", "init", folder, str(out)])
    assert "24 pages" in capsys.readouterr().out
    text = out.read_text()
    assert text.startswith("# written by linecaster benchmark init")
    assert "# script Hans (recorded on 12 pages): written without spaces" in text
    bench = read_benchmark(yaml.safe_load(io.StringIO(text)))
    assert bench.id == "bench" and bench.lanes == ["diplomatic", "reading"]
    assert bench.dataset.repo == "example/truth@r1" and bench.dataset.importer == "page-xml-import"
    assert bench.supports.roles == ["header", "paragraph"] and bench.supports.boxes and bench.supports.reading_order
    assert bench.pages.sha256 == listing_sha256(bench.pages.ids) and len(bench.pages.ids) == 24
    assert bench.pages.rule is None
    # a stratified sample of one split
    main(["benchmark", "init", folder, str(out), "--id", "strata", "--stratify", "language", "--per-stratum", "2",
          "--sample-per-item", "1", "--split", "test:0.5", "--split", "train:0.5", "--seed", "3"])
    bench = read_benchmark(yaml.safe_load(out.read_text()))
    assert bench.id == "strata" and bench.strata == ["language"] and len(bench.pages.ids) <= 4
    assert bench.pages.rule["stratify"] == "language" and bench.pages.rule["split"] == "test"
    from linecaster.data.sample import split_of

    assert {split_of(3, pid.split("_")[0], {"test": 0.5, "train": 0.5}) for pid in bench.pages.ids} == {"test"}
    with pytest.raises(SystemExit):
        main(["benchmark", "init", folder, str(out), "--per-stratum", "2"])           # per_stratum needs stratify


def test_benchmark_init_needs_a_dataset_the_sources_do_not_name(tmp_path):
    from linecaster.evaluation.truth import benchmark

    t = _truth(["x"])
    t.source.dataset = None
    folder = _write(tmp_path / "truth", [_row("p1", t)])
    with pytest.raises(ValueError, match="dataset"):
        benchmark(folder, "b")
    data, _ = benchmark(folder, "b", dataset="example/other@r2")
    assert data["dataset"]["repo"] == "example/other@r2"


def test_script_notes():
    assert "without spaces" in script_note("Jpan") and "combining marks" in script_note("Deva")
    assert "right to left" in script_note("Hebr") and "diplomatic" in script_note("Latn")


def test_linecaster_truth_publish_writes_hub_parquet_and_a_card(tmp_path, capsys):
    import pyarrow.parquet as pq
    from PIL import Image

    from linecaster.cli import main

    images = tmp_path / "images"
    images.mkdir()
    Image.new("RGB", (10, 14), "white").save(images / "p1.png")
    t = _truth(["one"])
    t.source.normalized = ["long-s"]
    t.source.example__license = "CC0-1.0"
    rows = [_row("p1", t, image="https://library.test/iiif/p1.png"),
            _row("p2", _truth(["two"], language="he"), item="other")]
    folder = _write(tmp_path / "truth", rows)
    out = tmp_path / "hub"
    main(["truth", "publish", folder, str(out), "--images", str(images)])
    assert "pages 2 (with an image 1); train 2" in capsys.readouterr().out
    (file,) = (out / "data").iterdir()
    assert file.name == "train-00000-of-00001.parquet"
    table = pq.read_table(file)
    assert table.column_names == ["id", "item_id", "image", "text", "language", "script", "page"]
    assert json.loads(table.schema.metadata[b"huggingface"])["info"]["features"]["image"] == {"_type": "Image"}
    got = table.to_pylist()
    assert got[0]["image"]["bytes"][:4] == b"\x89PNG" and got[1]["image"] is None
    assert Page.model_validate(json.loads(got[0]["page"])).page_id == "p1"
    assert (got[0]["text"], got[0]["language"]) == (t.text, "en")
    card = (out / "README.md").read_text()
    front = yaml.safe_load(card.split("---")[1])
    assert front["license"] == "cc0-1.0" and front["language"] == ["en", "he"]
    assert front["configs"][0]["data_files"] == [{"split": "train", "path": "data/train-*"}]
    assert "`example/truth@r1` | 2" in card and "`long-s`: 1 pages" in card and "linecaster" in card
    # splits by item, records read again for their images (none here: the image cannot be read)
    main(["truth", "publish", folder, str(tmp_path / "split"), "--split", "a:0.5", "--split", "b:0.5",
          "--no-images", "--license", "CC-BY-4.0"])
    names = sorted(p.name.split("-")[0] for p in (tmp_path / "split/data").iterdir())
    assert sum(pq.read_table(p).num_rows for p in (tmp_path / "split/data").iterdir()) == 2 and names
    assert yaml.safe_load((tmp_path / "split/README.md").read_text().split("---")[1])["license"] == "cc0-1.0"
