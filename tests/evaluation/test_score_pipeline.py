"""``pipelines/score.py`` (``score.v1``): the run's pages scored over tasks (``PageScorer``, ``ScoreWriter``) and put
together on the driver (``aggregate``) give what ``linecaster score`` gives in one process; a page the run lacks
is scored as an empty output; the ground truth is read for the requested ids alone."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("rapidfuzz")

from test_score_run import IDS, _setup  # noqa: E402

from linecaster import cli  # noqa: E402
from linecaster.catalog import yamlio  # noqa: E402
from linecaster.templates import score as template  # noqa: E402
from linecaster.execution import run  # noqa: E402
from linecaster.evaluation.run import read_truth  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _score_pipeline(tmp_path: Path, monkeypatch, out: str = "scores-pipeline") -> Path:
    folder = tmp_path / out
    monkeypatch.setattr(sys, "argv", ["score.py", str(folder), "--pages", str(tmp_path / "run" / "pages"),
                                      "--ground-truth", str(tmp_path / "gt"), "--benchmark", str(tmp_path / "bench.yaml"),
                                      "--tasks", "2", "--workers", "1"])
    run.main(str(ROOT / "pipelines" / "score.py"), template.__doc__, template.options, template.models, template.pipeline,
             template.PIPELINE, template.SLOTS)
    return folder


def test_the_pipeline_scores_as_linecaster_score_does(tmp_path, monkeypatch, capsys):
    _setup(tmp_path)
    cli.main(["score", str(tmp_path / "run"), str(tmp_path / "gt"), "--benchmark", str(tmp_path / "bench.yaml")])
    folder = _score_pipeline(tmp_path, monkeypatch)
    printed = capsys.readouterr().out
    assert "pages 2, missing 0, failed 0; eligible" in printed
    one = yamlio.read(tmp_path / "run" / "scores" / "evidence.yaml")
    many = yamlio.read(folder / "evidence.yaml")
    assert one["metrics"] == many["metrics"] and one["counts"] == many["counts"]
    assert many["recipe"] == "squiddle" and many["run"]["run_id"] == "0" * 32      # the run record, found from --pages
    assert (folder / "scores.parquet").is_file() and sorted(p.name for p in (folder / "records").iterdir())


def test_a_page_the_run_lacks_is_scored_as_an_empty_output(tmp_path, monkeypatch, capsys):
    _setup(tmp_path)
    pages = tmp_path / "run" / "pages" / "00000.jsonl"
    lines = pages.read_text().splitlines()
    pages.write_text(lines[0] + "\n")                       # the run wrote only the first page
    _score_pipeline(tmp_path, monkeypatch)
    assert "pages 2, missing 1, failed 0; NOT eligible" in capsys.readouterr().out


def test_the_ground_truth_is_read_for_the_requested_pages_alone(tmp_path):
    _setup(tmp_path)
    got = read_truth(str(tmp_path / "gt"), {IDS[1]})
    assert list(got) == [IDS[1]] and got[IDS[1]]["page"]["page_id"] == IDS[1]
    assert read_truth(str(tmp_path / "gt"), set()) == {}
    assert read_truth(str(tmp_path / "gt"), {"no-such-page"}) == {}
    row = json.loads((tmp_path / "gt" / "00000.jsonl").read_text().splitlines()[0])
    assert list(row)[:2] == ["schema", "id"]                 # what the line's id is read from
