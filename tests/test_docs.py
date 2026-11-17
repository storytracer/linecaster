"""``linecaster docs`` writes the generated docs (and removes stale pages), and the README's "Your own pipeline"
builds."""
from __future__ import annotations

import re

from linecaster import cli
from linecaster.catalog import code
from linecaster.docs import SITE

README = code.REPO / "README.md"


def test_the_generator_writes_every_page_and_removes_stale_ones(tmp_path, capsys):
    out = tmp_path / "docs"
    (out / "components" / "readers").mkdir(parents=True)
    (out / "components" / "readers" / "stale.md").write_text("from an earlier run")
    cli.main(["docs", "--out", str(out), "--readme", str(README)])
    assert not (out / "components" / "readers" / "stale.md").exists()
    for page in ("index.md", "changelog.md", "llms.txt", "llms-full.txt", "components/README.md", "catalog/README.md",
                 "components/readers/ImageFolderReader.md"):
        assert (out / page).is_file(), page
    assert f"({SITE}/components/)" in (out / "llms.txt").read_text()
    failed = [p.relative_to(out).as_posix() for p in (out / "components").rglob("*.md") if "not built" in p.read_text()]
    assert failed == []                                        # every component builds for its page
    assert "stale.md" in capsys.readouterr().out
    cli.main(["docs", "--out", str(out), "--readme", str(README)])
    assert capsys.readouterr().out == ""                       # nothing changed: nothing written


def _own_pipeline_snippet() -> str:
    text = README.read_text(encoding="utf-8")
    section = re.split(r"^#+ .*Your own pipeline.*$", text, maxsplit=1, flags=re.M)[1].split("\n## ", 1)[0]
    return re.search(r"```python\n(.*?)```", section, re.S).group(1)


def test_the_readme_pipeline_builds_and_checks(tmp_path, monkeypatch):
    """The snippet as written, up to the executor: ``Pipeline.run`` checks the plan and hands its stages to the local
    executor, which is replaced here (no engine loads before a component's warm-up, so none is needed)."""
    import linecaster.execution.local as local

    stages = []

    class Executor:
        def __init__(self, pipeline, **kwargs):
            stages.append(pipeline)

        def run(self):
            pass

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(local, "LocalExecutor", Executor)
    exec(compile(_own_pipeline_snippet(), "README.md", "exec"), {})
    names = [type(step).__name__ for step in stages[0] if type(step).__name__ != "Boundary"]
    assert len(stages) == 1 and names[0] == "ImageFolderReader" and names[-1] == "PageFileWriter"
