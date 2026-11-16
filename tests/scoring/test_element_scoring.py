"""The element scorer: a page's elements (``linecaster.scoring.elements``), its counts attributed to them
(``edit_counts_by``), the reading order (``linecaster.scoring.order``), ``score_elements``' rows and their accounting,
the benchmark's element metrics and their hash, ``elements.parquet``, strata and evidence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("rapidfuzz")

from linecaster.data import Annotator, Page, Source, Transcription  # noqa: E402
from linecaster.data.sample import listing_sha256  # noqa: E402
from linecaster.scoring.counts import edit_counts, edit_counts_by  # noqa: E402
from linecaster.scoring.order import index_edits, kendall  # noqa: E402

IDS = ["library.test_item1_0001", "library.test_item1_0002"]


def _page(blocks, language: str | None = None) -> Transcription:
    """A page of regions (role, lines), in the order given."""
    t = Transcription(source=Source(image_width=1000, image_height=1000))
    a = t.add_annotator(Annotator(step="layout", name="test"))
    k = 0
    for r, (role, lines) in enumerate(blocks):
        t.add_region(a, f"r{r}", [0, 100 * r, 1000, 90], role=role)
        for s in lines:
            t.add_line(a, f"l{k}", region=f"r{r}", text=s)
            k += 1
    t.add_order(a, [r.id for r in t.regions], [ln.id for ln in t.lines])
    if language:
        t.classify(a, "", "language", language)
    return t


def _lines(lines) -> Transcription:
    """A page of lines without regions, as a model writing Markdown gives it."""
    t = Transcription(source=Source(image_width=1000, image_height=1000))
    a = t.add_annotator(Annotator(step="recognition", name="test"))
    for k, s in enumerate(lines):
        t.add_line(a, f"l{k}", text=s)
    t.add_order(a, [], [ln.id for ln in t.lines])
    return t


# ------------------------------------------------------------------------------------------- attribution

@pytest.mark.parametrize("segments, output", [
    (["the ship", "sailed far"], "the shop sailed fur away"),
    (["東京は", "晴れです"], "東京晴れでず。"),
    (["one", "two", "three"], ""),
    (["", "x"], "xyz"),
    (["prefix"], "an inserted prefix"),
])
def test_counts_attributed_to_segments_sum_to_the_joined_counts(segments, output):
    parts = edit_counts_by(segments, output)
    whole = edit_counts(" ".join(segments), output)
    for field in ("s", "d", "i", "h", "n"):
        assert sum(getattr(p, field) for p in parts) == getattr(whole, field)


def test_an_edit_counts_for_the_segment_it_falls_in():
    a, b = edit_counts_by(["the ship", "sailed far"], "the ship sailed fur")
    assert (a.s, a.d, a.i) == (0, 0, 0) and (b.s, b.d, b.i) == (1, 0, 0)


# ------------------------------------------------------------------------------------------- reading order

def test_kendall_counts_pairs_the_other_way_round_and_ignores_ties():
    assert kendall([0, 1, 2]) == (0, 3) and kendall([2, 1, 0]) == (3, 3) and kendall([0, 0, 1]) == (0, 2)


def test_the_index_edit_distance_is_omnidocbench_s_order_measure():
    assert index_edits([0, 1, 2]) == (0, 3) and index_edits([1, 0, 2]) == (2, 3)


# ------------------------------------------------------------------------------------------- elements

def test_elements_are_region_runs_tables_and_formulas_in_reading_order():
    from linecaster.scoring.elements import elements

    t = _page([("heading", ["Chapter One"]), ("paragraph", ["The ship sailed", "far away."])], language="en")
    es = elements(t)
    assert [(e.kind, e.role, e.content) for e in es] == [("text", "heading", "Chapter One"),
                                                          ("text", "paragraph", "The ship sailed\nfar away.")]
    assert ("language", "en") in es[0].attributes


def test_lines_without_regions_split_into_markdown_blocks():
    from linecaster.scoring.elements import elements

    es = elements(_lines(["# Chapter One", "Some text", "| Name | Year |", "|---|---|", "| Ship | 1850 |",
                          "$$", "E = mc^2", "$$"]))
    kinds = [(e.kind, e.role) for e in es]
    assert kinds[0] == ("text", "heading") and es[0].content == "Chapter One"
    assert ("formula", "formula") in kinds and next(e for e in es if e.kind == "formula").latex == "E = mc^2"
    tables = [e for e in es if e.table is not None or e.table_kind]
    assert tables and tables[0].table_kind is not None


def test_no_transcription_has_no_elements():
    from linecaster.scoring.elements import elements

    assert elements(None) == []


# ------------------------------------------------------------------------------------------- score_elements

def _truth():
    return _page([("heading", ["Chapter One"]), ("paragraph", ["The ship sailed from the harbor at dawn."]),
                  ("paragraph", ["The crew sang as the wind rose over the sea."])])


def test_an_output_in_another_order_scores_zero_element_cer_but_not_zero_page_cer():
    from linecaster.scoring import score_page
    from linecaster.scoring.metrics import score_elements

    truth = _truth()
    swapped = _page([("paragraph", ["The crew sang as the wind rose over the sea."]),
                     ("heading", ["Chapter One"]), ("paragraph", ["The ship sailed from the harbor at dawn."])])
    el = score_elements(truth, swapped, texts=("full",), lanes=("diplomatic",))
    rows = el["rows"]
    assert sum(r["s"] + r["d"] + r["i"] for r in rows) == 0
    assert el["page"]["order_discordant"] > 0 and el["page"]["order_edits"] > 0
    page = score_page(truth, swapped, texts=("full",), lanes=("diplomatic",))["rows"][0]
    assert page["s"] + page["d"] + page["i"] > 0


def test_element_rows_account_for_every_edit():
    from linecaster.scoring.metrics import ELEMENT_FIELDS, score_elements

    truth = _truth()
    output = _page([("heading", ["Chapter One"]), ("paragraph", ["The ship sailed from the harbr at dawn."]),
                    ("paragraph", ["A line nobody wrote on the page at all."])])
    el = score_elements(truth, output, texts=("full",), lanes=("diplomatic",))
    rows = el["rows"]
    assert all(set(r) == set(ELEMENT_FIELDS) for r in rows)                  # a constant key set
    truth_rows = [r for r in rows if r["side"] == "truth"]
    extra = [r for r in rows if r["side"] == "output"]
    assert [r["match"] for r in truth_rows] == ["one", "one", "missed"]
    assert truth_rows[1]["d"] == 1 and truth_rows[2]["d"] == truth_rows[2]["n"] and truth_rows[2]["h"] == 0
    assert len(extra) == 1 and extra[0]["i"] > 0 and extra[0]["n"] == 0
    assert sum(r["n"] for r in truth_rows) == sum(len(x) for x in ("Chapter One",
                                                                    "The ship sailed from the harbor at dawn.",
                                                                    "The crew sang as the wind rose over the sea."))
    assert all(r["m"] >= max(r["n"], r["h"] + r["s"] + r["i"]) for r in rows)


def test_a_missing_output_is_all_deletions():
    from linecaster.scoring.metrics import score_elements

    rows = score_elements(_truth(), None, texts=("full",), lanes=("diplomatic",))["rows"]
    assert all(r["match"] == "missed" and r["d"] == r["n"] for r in rows)


@pytest.mark.parametrize("sample", ["latin", "arabic", "devanagari", "japanese", "mongolian"])
def test_script_samples_in_every_direction_score_zero_against_themselves_and_split_by_their_writing(sample):
    from linecaster.scoring.metrics import score_elements
    from linecaster.testing.scripts import SCRIPT_SAMPLES, script_page

    page = script_page(sample)
    el = score_elements(page, page, texts=("full",), lanes=("diplomatic",))
    rows = el["rows"]
    assert rows and sum(r["s"] + r["d"] + r["i"] for r in rows) == 0
    assert {r["match"] for r in rows} == {"one"} and el["page"]["order_discordant"] == 0
    assert ["script", SCRIPT_SAMPLES[sample].script] in rows[0]["attributes"]


# ------------------------------------------------------------------------------------------- benchmarks and runs

def _bench(**fields):
    from linecaster.scoring.benchmark import Benchmark

    return Benchmark.model_validate({"schema": "linecaster.benchmark/2", "id": "b",
                                     "dataset": {"repo": "x@1", "importer": "alto"},
                                     "pages": {"ids": IDS, "sha256": listing_sha256(IDS)}, **fields})


def test_the_default_metrics_are_the_element_metrics_and_the_page_ones():
    from linecaster.scoring.benchmark import ELEMENT_METRICS

    b = _bench()
    assert {"elements", "tables", "formulas", "cer", "token_recall"} <= set(b.metrics)
    assert "reading_order" not in b.metrics                                  # supports no reading order
    assert "reading_order" in _bench(supports={"reading_order": True}).metrics
    assert b.element_metrics and not _bench(metrics=["cer"]).element_metrics
    assert set(ELEMENT_METRICS) - {"reading_order"} <= set(b.metrics)
    with pytest.raises(ValueError):
        _bench(metrics=["reading_order"])


def test_element_settings_are_in_the_hash_only_with_element_metrics():
    old = ["cer", "token_recall", "over_extraction"]
    assert _bench(metrics=old).sha256 == _bench(metrics=old, elements={"containment": 0.7}).sha256
    assert _bench().sha256 != _bench(elements={"containment": 0.7}).sha256
    assert _bench().sha256 == _bench(elements={"containment": 0.5}).sha256


def _records(folder: Path, name: str, transcriptions: dict) -> None:
    folder.mkdir(parents=True)
    with open(folder / "00000.jsonl", "w") as f:
        for pid, t in transcriptions.items():
            page = Page(page_id=pid, item_id="library.test_item1", transcriptions={name: t})
            f.write(json.dumps({"schema": "linecaster.page/3", "id": pid, "text": t.text, "page": page.record()})
                    + "\n")


def _run(tmp_path: Path):
    from linecaster.catalog import yamlio

    truth = {pid: _truth() for pid in IDS}
    for t in truth.values():
        t.source.kind, t.annotators[0].kind = "ground_truth", "human"
    swapped = _page([("paragraph", ["The crew sang as the wind rose over the sea."]),
                     ("heading", ["Chapter One"]), ("paragraph", ["The ship sailed from the harbr at dawn."])])
    _records(tmp_path / "gt", "ground_truth", truth)
    _records(tmp_path / "run" / "pages", "ocr_new", {IDS[0]: _truth(), IDS[1]: swapped})
    (tmp_path / "run" / "run.yaml").write_text(yamlio.dump({"run_id": "0" * 32, "recipe": {"ref": "squiddle"}}))
    bench = {"schema": "linecaster.benchmark/2", "id": "test-gt", "dataset": {"repo": "example.org/gt@0123abc",
                                                                              "importer": "docling"},
             "pages": {"ids": IDS, "sha256": listing_sha256(IDS)}, "supports": {"reading_order": True},
             "lanes": ["diplomatic"], "strata": ["match"], "bootstrap": {"seed": 0, "resamples": 20}}
    (tmp_path / "bench.yaml").write_text(yamlio.dump(bench))


def test_a_run_s_element_rates_strata_parquet_and_evidence(tmp_path):
    import pyarrow.parquet as pq

    from linecaster import cli
    from linecaster.catalog import yamlio

    _run(tmp_path)
    cli.main(["score", str(tmp_path / "run"), str(tmp_path / "gt"), "--benchmark", str(tmp_path / "bench.yaml")])
    scores = tmp_path / "run" / "scores"
    ev = yamlio.read(scores / "evidence.yaml")
    m = ev["metrics"]
    assert 0 < m["element_cer_full_diplomatic"]["value"] < m["cer_full_diplomatic"]["value"]
    assert m["order_kendall"]["value"] > 0 and m["order_kendall"]["n"] == 2
    assert ev["scoring"]["elements"]["version"] >= 1 and ev["scoring"]["elements"]["lane"]["id"] == "diplomatic"
    assert set(ev["strata"]) >= {"role", "kind", "match"}
    assert ev["strata"]["role"]["heading"]["pages"] == 2
    assert ev["strata"]["role"]["heading"]["metrics"]["element_cer"]["value"] == 0
    elements = pq.read_table(scores / "elements.parquet").to_pylist()
    assert elements and {r["level"] for r in elements} == {"element"}
    pages = pq.read_table(scores / "scores.parquet").to_pylist()
    assert all(r.get("level") != "element" for r in pages)


def test_the_score_pipeline_gives_score_run_s_element_rates(tmp_path):
    from linecaster.catalog import yamlio
    from linecaster.data.policy import DEFAULT_POLICY
    from linecaster.scoring.benchmark import read_benchmark
    from linecaster.scoring.run import score_pair, score_run, summarize

    _run(tmp_path)
    bench = read_benchmark(yamlio.read(tmp_path / "bench.yaml"))
    whole = score_run(tmp_path / "run" / "pages", tmp_path / "gt", bench)
    from linecaster.scoring.run import read_records

    truths = {r["id"]: r for r in read_records(tmp_path / "gt")}
    outs = {r["id"]: r for r in read_records(tmp_path / "run" / "pages")}
    records, pages = [], []
    for pid in reversed(IDS):                                                # page by page, in any order
        recs, summary = score_pair(pid, truths[pid], outs[pid], bench, "ocr_new", DEFAULT_POLICY)
        records += recs
        pages.append(summary)
    parts = summarize(records, pages, bench, warn=False)
    for k in ("element_cer_full_diplomatic", "order_kendall", "order_edit"):
        assert parts["rates"][k]["value"] == pytest.approx(whole["rates"][k]["value"])


def test_evidence_compares_the_element_metrics():
    from linecaster.catalog.schema import Evidence3

    def ev(elements=None):
        named = {"id": "x", "sha256": "sha256:" + "1" * 64}
        scoring = {"policy": named, "output": named, "lanes": [named], "unit": "grapheme", "scorer": "linecaster x"}
        if elements is not None:
            scoring["elements"] = elements
        return Evidence3.model_validate({"schema": "linecaster.evidence/3", "recipe": "r", "source": "own-run",
                                         "benchmark": {"ref": "b@1", "sha256": "sha256:" + "0" * 64},
                                         "scoring": scoring, "metrics": {}, "date": "2026-11-16"})

    lane = {"id": "x", "sha256": "sha256:" + "1" * 64}
    now = {"version": 1, "lane": lane}
    assert ev(now).comparable(ev(now))
    assert not ev(now).comparable(ev())
    assert not ev(now).comparable(ev({"version": 2, "lane": lane}))
    assert not ev(now).comparable(ev({"version": 1, "lane": {"id": "y", "sha256": "sha256:" + "2" * 64}}))
