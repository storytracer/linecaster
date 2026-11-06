"""The generated docs are current (``linecaster docs --check``), and the README's "Your own pipeline" builds."""
from __future__ import annotations

import re

import datatrove.executor
import pytest

from linecaster import cli, docs
from linecaster.catalog import code

README = code.REPO / "README.md"


def test_the_docs_are_current():
    files = docs.generate(code.REPO / "docs", README)
    assert docs.check(files, code.REPO / "docs") == [], "run `linecaster docs`"


def test_check_names_each_differing_file_and_writes_nothing(tmp_path, monkeypatch, capsys):
    readme = tmp_path / "README.md"
    readme.write_text("intro\n<!-- blocks:start -->\nold\n<!-- blocks:end -->\n")
    (tmp_path / "docs" / "blocks").mkdir(parents=True)
    (tmp_path / "docs" / "blocks" / "stale.md").write_text("from an earlier run")
    with pytest.raises(SystemExit) as e:
        cli.main(["docs", "--out", str(tmp_path / "docs"), "--readme", str(readme), "--check"])
    assert e.value.code == 1
    out = capsys.readouterr().out
    assert f"differs: {readme}" in out and "stale.md" in out and "LineRecognizer.md" in out
    assert readme.read_text().endswith("old\n<!-- blocks:end -->\n") and not (tmp_path / "docs" / "index.md").exists()
    cli.main(["docs", "--out", str(tmp_path / "docs"), "--readme", str(readme)])
    assert not (tmp_path / "docs" / "blocks" / "stale.md").exists()
    cli.main(["docs", "--out", str(tmp_path / "docs"), "--readme", str(readme), "--check"])
    assert capsys.readouterr().out.strip().endswith("docs current")


def _own_pipeline_snippet() -> str:
    text = README.read_text(encoding="utf-8")
    section = re.split(r"^#+ .*Your own pipeline.*$", text, maxsplit=1, flags=re.M)[1].split("\n## ", 1)[0]
    return re.search(r"```python\n(.*?)```", section, re.S).group(1)


def test_the_readme_pipeline_builds_and_checks(tmp_path, monkeypatch):
    """The snippet as written, up to the executor: its ``run()`` builds the plan and checks it instead (no engine
    loads before a block's warm-up, so none is needed)."""
    from linecaster.runtime.builder import build

    plans = []

    class Executor:
        def __init__(self, pipeline, logging_dir=None, **kwargs):
            self.pipeline = pipeline

        def run(self):
            plan = build(self.pipeline)
            plan.check()
            plans.append(plan)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(datatrove.executor, "LocalPipelineExecutor", Executor)
    exec(compile(_own_pipeline_snippet(), "README.md", "exec"), {})
    assert len(plans) == 1 and [type(b).__name__ for b in plans[0].stages[0].blocks][-1] == "PageFileWriter"
