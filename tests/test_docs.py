"""``linecaster docs`` writes the generated docs (and removes stale pages), and the README's "Your own pipeline"
builds."""
from __future__ import annotations

import re

import datatrove.executor

from linecaster import cli
from linecaster.catalog import code
from linecaster.docs import SITE

README = code.REPO / "README.md"


def test_the_generator_writes_every_page_and_removes_stale_ones(tmp_path, capsys):
    out = tmp_path / "docs"
    (out / "blocks" / "readers").mkdir(parents=True)
    (out / "blocks" / "readers" / "stale.md").write_text("from an earlier run")
    cli.main(["docs", "--out", str(out), "--readme", str(README)])
    assert not (out / "blocks" / "readers" / "stale.md").exists()
    for page in ("index.md", "changelog.md", "llms.txt", "llms-full.txt", "blocks/README.md", "catalog/README.md",
                 "blocks/readers/ImageFolderReader.md"):
        assert (out / page).is_file(), page
    assert f"({SITE}/blocks/)" in (out / "llms.txt").read_text()
    assert "stale.md" in capsys.readouterr().out
    cli.main(["docs", "--out", str(out), "--readme", str(README)])
    assert capsys.readouterr().out == ""                       # nothing changed: nothing written


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
