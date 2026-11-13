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
                                                            "recipe": {"ref": "squiddle@1"}}))
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
    assert ev["schema"] == "linecaster.evidence/2" and ev["recipe"] == "squiddle@1"
    assert ev["run"]["run_id"] == "0" * 32 and ev["run"]["pipeline_sha256"] == "sha256:" + "1" * 64
    assert ev["benchmark"]["ref"] == "test-gt@1" and ev["scoring"]["policy"] == "page-layers@1"
    assert ev["scoring"]["lanes"] == ["diplomatic@1", "alnum@1"] and ev["counts"]["missing"] == 0
    cer = ev["metrics"]["cer_full_diplomatic"]
    assert 0 < cer["value"] < 0.01 and cer["n"] == 2
    assert ev["metrics"]["role_recall_header"]["value"] == 1.0
    import pyarrow.parquet as pq

    rows = pq.read_table(tmp_path / "run" / "scores" / "scores.parquet").to_pylist()
    assert len(rows) == 2 * 2 * 2 and {r["benchmark"] for r in rows} == {"test-gt@1"}
    assert sum(r["s"] for r in rows if r["text"] == "full" and r["lane"] == "diplomatic@1") == 1


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
    assert "cer_full_alnum" in capsys.readouterr().out
    other = yamlio.read(ev)
    other["scoring"]["lanes"] = ["diplomatic@1"]
    (tmp_path / "other.yaml").write_text(yamlio.dump(other))
    with pytest.raises(SystemExit):
        cli.main(["evidence", "compare", str(ev), str(tmp_path / "other.yaml")])


def test_a_benchmark_checks_its_page_set_and_what_its_ground_truth_supports():
    from linecaster.scoring.benchmark import Benchmark

    base = {"schema": "linecaster.benchmark/1", "id": "b", "dataset": {"repo": "x@1", "importer": "alto"},
            "pages": {"ids": IDS, "sha256": listing_sha256(IDS)}}
    assert Benchmark.model_validate(base).sha256 == Benchmark.model_validate({**base, "description": "x"}).sha256
    for bad in ({"pages": {"ids": IDS, "sha256": "sha256:0"}}, {"dataset": {"repo": "x", "importer": "alto"}},
                {"metrics": ["confusion"]}, {"lanes": ["nowhere@1"]}):
        with pytest.raises(ValueError):
            Benchmark.model_validate({**base, **bad})
