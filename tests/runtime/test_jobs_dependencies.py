"""``linecaster.runtime.jobs.dependencies``: a Job's ``uv run --with`` requirements from a pipeline script, its sources
spelled out as PEP 508 URLs, for linecaster's scripts and for a derivative's script outside the checkout."""
import pytest

from linecaster.errors import PipelineConfigError
from linecaster.runtime import jobs

REPO = "https://github.com/storytracer/linecaster"
ARCHIVE = f"{REPO}/archive/abc123.tar.gz"


def script(tmp_path, dependencies: list[str], sources: dict[str, str], lock: str | None = None, name="pipe.py"):
    """A derivative's script in ``tmp_path`` (outside the linecaster checkout), with its lock if given."""
    lines = ["# /// script", '# requires-python = ">=3.12,<3.13"', "# dependencies = ["]
    lines += [f'#     "{d}",' for d in dependencies]
    lines += ["# ]", "#", "# [tool.uv.sources]"] + [f"# {k} = {v}" for k, v in sources.items()] + ["# ///", ""]
    path = tmp_path / name
    path.write_text("\n".join(lines))
    if lock is not None:
        path.with_name(name + ".lock").write_text(lock)
    return path


def test_git_sources_with_tag_branch_rev_and_subdirectory(tmp_path):
    """A git source keeps its tag, branch or rev and its subdirectory (``git+URL@REF#subdirectory=DIR``)."""
    s = script(tmp_path, ["linecaster", "linecaster-kraken", "linecaster-paddlex", "kraken", "tool"], {
        "linecaster": f'{{ git = "{REPO}", tag = "v0.3.2" }}',
        "linecaster-kraken": f'{{ git = "{REPO}", tag = "v0.3.2", subdirectory = "engines/kraken" }}',
        "linecaster-paddlex": f'{{ git = "{REPO}", branch = "main", subdirectory = "engines/paddlex" }}',
        "kraken": '{ git = "https://github.com/storytracer/kraken", rev = "48eecb78" }',
        "tool": '{ git = "https://example.org/tool.git" }',
    })
    assert jobs.dependencies("abc123", s) == [
        f"linecaster @ git+{REPO}@v0.3.2",
        f"linecaster-kraken @ git+{REPO}@v0.3.2#subdirectory=engines/kraken",
        f"linecaster-paddlex @ git+{REPO}@main#subdirectory=engines/paddlex",
        "kraken @ git+https://github.com/storytracer/kraken@48eecb78",
        "tool @ git+https://example.org/tool.git",
    ]


def test_extras_markers_url_sources_and_plain_requirements(tmp_path):
    """linecaster's extras without ``ray`` (a Job does not use Ray), markers kept, a ``url`` source as it is (with its
    subdirectory), a requirement without a source as it is."""
    s = script(tmp_path, ["linecaster[ray,pybookget]", "pybookget", "stub ; sys_platform == 'linux'", "s3fs>=2025.3"], {
        "linecaster": f'{{ git = "{REPO}", tag = "v0.3.2" }}',
        "pybookget": '{ url = "https://example.org/pybookget.tar.gz" }',
        "stub": '{ url = "https://example.org/repo.tar.gz", subdirectory = "stubs/stub" }',
    })
    assert jobs.dependencies("abc123", s) == [
        f"linecaster[pybookget] @ git+{REPO}@v0.3.2",
        "pybookget @ https://example.org/pybookget.tar.gz",
        "stub @ https://example.org/repo.tar.gz#subdirectory=stubs/stub ; sys_platform == 'linux'",
        "s3fs>=2025.3",
    ]
    assert jobs.dependencies("abc123", s, engines=False) == [f"linecaster[pybookget] @ git+{REPO}@v0.3.2"]


def test_a_path_outside_the_checkout_is_an_error(tmp_path):
    """A Job has no copy of a local folder outside the linecaster checkout."""
    (tmp_path / "mypkg").mkdir()
    s = script(tmp_path, ["mypkg"], {"mypkg": '{ path = "mypkg" }'})
    with pytest.raises(PipelineConfigError, match="mypkg comes from the folder"):
        jobs.dependencies("abc123", s)


def test_a_path_into_the_checkout_is_linecaster_at_the_commit(tmp_path):
    """A derivative developed against a linecaster checkout (``path = ".../linecaster"``): the Jobs install linecaster
    at ``commit``, as with linecaster's own scripts."""
    s = script(tmp_path, ["linecaster", "linecaster-tesseract"], {
        "linecaster": f'{{ path = "{jobs.ROOT}", editable = true }}',
        "linecaster-tesseract": f'{{ path = "{jobs.ROOT / "engines" / "tesseract"}", editable = true }}',
    })
    assert jobs.dependencies("abc123", s) == [
        f"linecaster @ {ARCHIVE}", f"linecaster-tesseract @ {ARCHIVE}#subdirectory=engines/tesseract"]


LOCK = f"""
version = 1
requires-python = "==3.12.*"

[[package]]
name = "linecaster"
version = "0.3.2"
source = {{ git = "{REPO}?tag=v0.3.2#0123456789abcdef" }}
dependencies = [{{ name = "numpy" }}]

[package.optional-dependencies]
pybookget = [{{ name = "pybookget" }}]
ray = [{{ name = "rayish" }}]

[[package]]
name = "linecaster-kraken"
version = "0.1.2"
source = {{ git = "{REPO}?subdirectory=engines%2Fkraken&tag=v0.3.2#0123456789abcdef" }}
dependencies = [{{ name = "kraken" }}, {{ name = "linecaster" }}, {{ name = "torch" }}]

[[package]]
name = "kraken"
version = "7.1.post18"
source = {{ git = "https://github.com/storytracer/kraken?rev=48eecb78#48eecb78a8e043b1c658042fcb7c357f68aa786c" }}

[[package]]
name = "pybookget"
version = "1.2.0"
source = {{ url = "https://example.org/pybookget.tar.gz" }}

[[package]]
name = "rayish"
version = "1.0"
source = {{ url = "https://example.org/rayish.tar.gz" }}

[[package]]
name = "numpy"
version = "2.3.0"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "torch"
version = "2.14.0"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "unrelated"
version = "1.0"
source = {{ url = "https://example.org/unrelated.tar.gz" }}
"""


def test_the_installed_packages_own_sources_come_from_the_lock(tmp_path):
    """The sources the installed packages declare themselves (uv lock applied them, uv run --with would not): every
    package reachable from the script's dependencies that does not come from an index, a git one at its locked
    commit; extras count only when asked for (not ``ray``), and what is not reachable is left out."""
    s = script(tmp_path, ["linecaster[ray,pybookget]", "linecaster-kraken"], {
        "linecaster": f'{{ git = "{REPO}", tag = "v0.3.2" }}',
        "linecaster-kraken": f'{{ git = "{REPO}", tag = "v0.3.2", subdirectory = "engines/kraken" }}',
    }, lock=LOCK)
    assert jobs.dependencies("abc123", s) == [
        f"linecaster[pybookget] @ git+{REPO}@v0.3.2",
        f"linecaster-kraken @ git+{REPO}@v0.3.2#subdirectory=engines/kraken",
        "kraken @ git+https://github.com/storytracer/kraken@48eecb78a8e043b1c658042fcb7c357f68aa786c",
        "pybookget @ https://example.org/pybookget.tar.gz",
    ]
    assert jobs.dependencies("abc123", s, engines=False) == [
        f"linecaster[pybookget] @ git+{REPO}@v0.3.2", "pybookget @ https://example.org/pybookget.tar.gz"]


def test_without_a_script():
    assert jobs.dependencies("abc123", engines=False) == [f"linecaster @ {ARCHIVE}"]
    with pytest.raises(PipelineConfigError, match="give the pipeline's script"):
        jobs.dependencies("abc123")
