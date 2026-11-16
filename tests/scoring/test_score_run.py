"""``linecaster score`` end to end: a run's page records against a ground truth's, by a benchmark, into score
records and an evidence record that names the run, the benchmark and the scoring; ``linecaster evidence``."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("rapidfuzz")

from linecaster import cli  # noqa: E402
from linecaster.catalog import yamlio  # noqa: E402
from linecaster.data import Page  # noqa: E402
from linecaster.data.sample import listing_sha256  # noqa: E402
from linecaster.testing import sample_transcription  # noqa: E402

IDS = ["library.test_item1_0001", "library.test_item1_0002"]


def _records(folder: Path, name: str, transcriptions: dict) -> None:
    folder.mkdir(parents=True)
    with open(folder / "00000.jsonl", "w") as f:
        for pid, t in transcriptions.items():
            page = Page(page_id=pid, item_id="library.test_item1", transcriptions={name: t})
            f.write(json.dumps({"schema": "linecaster.page/3", "id": pid, "text": t.text, "page": page.record()})
                    + "\n")


def _setup(tmp_path: Path, misread: bool = True):
    truth = {}
    for pid in IDS:
        t = sample_transcription()
        t.source.kind, t.annotators[0].kind = "ground_truth", "human"
        truth[pid] = t
    out = {}
    for pid in IDS:
        t = sample_transcription()
        if misread and pid == IDS[1]:
            t.lines[2].reading.text = t.lines[2].reading.text.replace("species", "spccies")
        out[pid] = t
    _records(tmp_path / "gt", "ground_truth", truth)
    _records(tmp_path / "run" / "pages", "ocr_new", out)
    (tmp_path / "run" / "run.yaml").write_text(yamlio.dump({"run_id": "0" * 32, "pipeline_sha256": "sha256:" + "1" * 64,
                                                            "recipe": {"ref": "squiddle"}}))
    bench = {"schema": "linecaster.benchmark/1", "id": "test-gt", "edition": 1,
             "dataset": {"repo": "example.org/gt@0123abc", "importer": "docling"},
             "pages": {"ids": IDS, "sha256": listing_sha256(IDS)}, "supports": {"roles": ["header", "footnote"]},
             "lanes": ["diplomatic@1", "alnum@1"], "metrics": ["cer", "token_recall", "role_words"],
             "bootstrap": {"seed": 0, "resamples": 50}}
    (tmp_path / "bench.yaml").write_text(yamlio.dump(bench))


def test_score_writes_scores_and_evidence_that_name_what_was_measured(tmp_path, capsys):
    _setup(tmp_path)
    cli.main(["score", str(tmp_path / "run"), str(tmp_path / "gt"), "--benchmark", str(tmp_path / "bench.yaml")])
    printed = capsys.readouterr().out
    assert "eligible" in printed and "cer_full_diplomatic" in printed
    ev = yamlio.read(tmp_path / "run" / "scores" / "evidence.yaml")
    assert ev["schema"] == "linecaster.evidence/3" and ev["recipe"] == "squiddle"
    assert ev["run"]["run_id"] == "0" * 32 and ev["run"]["pipeline_sha256"] == "sha256:" + "1" * 64
    assert ev["benchmark"]["ref"] == "test-gt@1" and ev["scoring"]["policy"]["id"] == "page-layers"
    assert [x["id"] for x in ev["scoring"]["lanes"]] == ["diplomatic", "alnum-nonmark"]      # benchmark/1, upgraded
    assert all(x["sha256"].startswith("sha256:") for x in ev["scoring"]["lanes"]) and ev["counts"]["missing"] == 0
    assert ev["scoring"]["unit"] == "codepoint" and ev["scoring"]["output"]["id"] == "literal"
    assert ev["scoring"]["scorer"].startswith("linecaster ")
    cer = ev["metrics"]["cer_full_diplomatic"]
    assert 0 < cer["value"] < 0.01 and cer["n"] == 2
    assert ev["metrics"]["role_recall_header"]["value"] == 1.0
    # the slices: every page in those its ground truth meets, each slice with its rates
    from linecaster.scoring.slices import SLICES, page_slices

    want = page_slices(sample_transcription(), "")
    assert set(ev["slices"]) == set(want) and all(ev["slices"][k]["pages"] == 2 for k in want)
    assert {ev["slices"][k]["definition"] for k in want} <= set(SLICES.values())
    assert ev["slices"][want[0]]["metrics"]["cer_full_diplomatic"] == cer
    import pyarrow.parquet as pq

    rows = pq.read_table(tmp_path / "run" / "scores" / "scores.parquet").to_pylist()
    assert len(rows) == 2 * 2 * 2 and {r["benchmark"] for r in rows} == {"test-gt@1"}
    assert sum(r["s"] for r in rows if r["text"] == "full" and r["lane"] == "diplomatic") == 1


def test_a_run_missing_pages_is_not_eligible(tmp_path, capsys):
    _setup(tmp_path, misread=False)
    lines = (tmp_path / "run" / "pages" / "00000.jsonl").read_text().splitlines()
    (tmp_path / "run" / "pages" / "00000.jsonl").write_text(lines[0] + "\n")
    cli.main(["score", str(tmp_path / "run"), str(tmp_path / "gt"), "--benchmark", str(tmp_path / "bench.yaml")])
    assert "NOT eligible" in capsys.readouterr().out


def test_evidence_compare_only_like_with_like(tmp_path, capsys):
    _setup(tmp_path)
    cli.main(["score", str(tmp_path / "run"), str(tmp_path / "gt"), "--benchmark", str(tmp_path / "bench.yaml")])
    ev = tmp_path / "run" / "scores" / "evidence.yaml"
    cli.main(["evidence", "check", str(ev)])
    cli.main(["evidence", "compare", str(ev), str(ev)])
    assert "cer_full_alnum-nonmark" in capsys.readouterr().out
    other = yamlio.read(ev)
    other["scoring"]["lanes"] = other["scoring"]["lanes"][:1]
    (tmp_path / "other.yaml").write_text(yamlio.dump(other))
    with pytest.raises(SystemExit):
        cli.main(["evidence", "compare", str(ev), str(tmp_path / "other.yaml")])


def test_a_benchmark_checks_its_page_set_and_what_its_ground_truth_supports():
    from linecaster.scoring.benchmark import Benchmark, read_benchmark

    base = {"schema": "linecaster.benchmark/2", "id": "b", "dataset": {"repo": "x@1", "importer": "alto"},
            "pages": {"ids": IDS, "sha256": listing_sha256(IDS)}}
    assert Benchmark.model_validate(base).sha256 == Benchmark.model_validate({**base, "description": "x"}).sha256
    assert Benchmark.model_validate(base).sha256 != Benchmark.model_validate({**base, "unit": "codepoint"}).sha256
    for bad in ({"pages": {"ids": IDS, "sha256": "sha256:0"}}, {"dataset": {"repo": "x", "importer": "alto"}},
                {"metrics": ["confusion"]}, {"lanes": ["nowhere"]}, {"output": "casefold"}):
        with pytest.raises(ValueError):
            Benchmark.model_validate({**base, **bad})
    old = read_benchmark({**base, "schema": "linecaster.benchmark/1", "lanes": ["alnum@2", "alnum@1"]})
    assert (old.lanes, old.unit, old.schema_) == (["alnum", "alnum-nonmark"], "codepoint", "linecaster.benchmark/2")
    with pytest.raises(ValueError, match="unknown benchmark format"):
        read_benchmark({**base, "schema": "linecaster.benchmark/9"})


def test_evidence_from_before_0_10_is_read_upgraded_and_compared_with_none():
    from linecaster.catalog.schema import Evidence3, read_evidence

    old = {"schema": "linecaster.evidence/2", "recipe": "squiddle@2", "source": "own-run",
           "benchmark": {"ref": "b@1", "sha256": "sha256:" + "0" * 64},
           "scoring": {"policy": "page-layers@1", "lanes": ["alnum@2"], "scorer": "linecaster-scorer@1"},
           "metrics": {"cer": {"value": 0.1}}, "date": "2026-11-14"}
    ev = read_evidence(old)
    assert isinstance(ev, Evidence3) and ev.upgraded_from == "linecaster.evidence/2"
    assert [x.id for x in ev.scoring.lanes] == ["alnum"] and ev.scoring.unit == "codepoint"
    assert not ev.comparable(ev)                      # no hashes: comparable to no record


def test_the_conventions_check_warns_where_a_lane_does_not_apply_the_ground_truths_normalizations(tmp_path, capsys):
    """A ground truth that declares what its transcription already is (``Source.normalized``): each score record
    names what the lane does not apply (``conventions``), and the run warns of it once per lane."""
    from linecaster.scoring.lanes import uncovered
    from linecaster.scoring.run import ConventionsWarning

    assert uncovered(["nfc", "long-s", "r-rotunda"], "alnum") == ["r-rotunda"]          # nfkc subsumes long-s
    assert uncovered(["long-s"], "diplomatic") == ["long-s"]
    assert uncovered(["long-s"], "diplomatic", output="latin-historic") == []           # the output strategy does
    assert uncovered(["divided-words"], "alnum", output="unicode-marks+flow") == ["divided-words"]   # structure: no
    _setup(tmp_path)
    for f in (tmp_path / "gt").glob("*.jsonl"):
        rows = [json.loads(x) for x in f.read_text().splitlines()]
        for r in rows:
            r["page"]["transcriptions"]["ground_truth"]["source"]["normalized"] = ["nfc", "long-s"]
        f.write_text("".join(json.dumps(r) + "\n" for r in rows))
    with pytest.warns(ConventionsWarning, match="lane diplomatic: the ground truth already applies long-s"):
        cli.main(["score", str(tmp_path / "run"), str(tmp_path / "gt"), "--benchmark", str(tmp_path / "bench.yaml")])
    assert "conventions: lane diplomatic does not apply long-s" in capsys.readouterr().out
    import pyarrow.parquet as pq

    rows = pq.read_table(tmp_path / "run" / "scores" / "scores.parquet").to_pylist()
    assert {r["lane"]: tuple(r["conventions"]) for r in rows} == {"diplomatic": ("long-s",),
                                                                 "alnum-nonmark": ("long-s",)}
