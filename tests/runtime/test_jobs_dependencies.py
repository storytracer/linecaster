"""``linecaster.runtime.jobs.dependencies``: a Job's requirements from a pipeline script, its sources spelled out as
PEP 508 URLs, the lock's versions as constraints and the script's overrides, for linecaster's scripts and for a
derivative's script outside the checkout; and how ``JobsExecutor`` hands them to a Job (no Job is launched)."""
import argparse

import pytest

from linecaster.errors import PipelineConfigError
from linecaster.runtime import jobs

REPO = "https://github.com/storytracer/linecaster"
ARCHIVE = f"{REPO}/archive/abc123.tar.gz"


def script(tmp_path, dependencies: list[str], sources: dict[str, str], lock: str | None = None, name="pipe.py",
           overrides: list[str] | None = None):
    """A derivative's script in ``tmp_path`` (outside the linecaster checkout), with its lock if given."""
    lines = ["# /// script", '# requires-python = ">=3.12,<3.13"', "# dependencies = ["]
    lines += [f'#     "{d}",' for d in dependencies]
    lines += ["# ]", "#"]
    if overrides:
        lines += ["# [tool.uv]", "# override-dependencies = ["] + [f'#     "{o}",' for o in overrides] + ["# ]", "#"]
    lines += ["# [tool.uv.sources]"] + [f"# {k} = {v}" for k, v in sources.items()] + ["# ///", ""]
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
    assert jobs.dependencies("abc123", s).requirements == [
        f"linecaster @ git+{REPO}@v0.3.2",
        f"linecaster-kraken @ git+{REPO}@v0.3.2#subdirectory=engines/kraken",
        f"linecaster-paddlex @ git+{REPO}@main#subdirectory=engines/paddlex",
        "kraken @ git+https://github.com/storytracer/kraken@48eecb78",
        "tool @ git+https://example.org/tool.git",
    ]


def test_extras_markers_url_sources_and_plain_requirements(tmp_path):
    """linecaster's extras without ``ray`` (a Job does not use Ray), markers kept, a ``url`` source as it is (with its
    subdirectory), a requirement without a source as it is."""
    s = script(tmp_path, ["linecaster[ray,urlpkg]", "urlpkg", "stub ; sys_platform == 'linux'", "tool>=1.0"], {
        "linecaster": f'{{ git = "{REPO}", tag = "v0.3.2" }}',
        "urlpkg": '{ url = "https://example.org/urlpkg.tar.gz" }',
        "stub": '{ url = "https://example.org/repo.tar.gz", subdirectory = "stubs/stub" }',
    })
    assert jobs.dependencies("abc123", s).requirements == [
        f"linecaster[urlpkg] @ git+{REPO}@v0.3.2",
        "urlpkg @ https://example.org/urlpkg.tar.gz",
        "stub @ https://example.org/repo.tar.gz#subdirectory=stubs/stub ; sys_platform == 'linux'",
        "tool>=1.0",
    ]
    assert jobs.dependencies("abc123", s, engines=False).requirements == [f"linecaster[urlpkg] @ git+{REPO}@v0.3.2"]


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
    assert jobs.dependencies("abc123", s).requirements == [
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
urlpkg = [{{ name = "urlpkg" }}]
ray = [{{ name = "rayish" }}]

[[package]]
name = "linecaster-kraken"
version = "0.1.2"
source = {{ git = "{REPO}?subdirectory=engines%2Fkraken&tag=v0.3.2#0123456789abcdef" }}
dependencies = [{{ name = "kraken" }}, {{ name = "linecaster" }}, {{ name = "torch" }}, {{ name = "forked" }}]

[[package]]
name = "kraken"
version = "7.1.post18"
source = {{ git = "https://github.com/storytracer/kraken?rev=48eecb78#48eecb78a8e043b1c658042fcb7c357f68aa786c" }}

[[package]]
name = "urlpkg"
version = "1.2.0"
source = {{ url = "https://example.org/urlpkg.tar.gz" }}

[[package]]
name = "rayish"
version = "1.0"
source = {{ url = "https://example.org/rayish.tar.gz" }}
dependencies = [{{ name = "grpcish" }}]

[[package]]
name = "grpcish"
version = "1.0"
source = {{ registry = "https://index.example.org/simple" }}

[[package]]
name = "numpy"
version = "2.3.0"
source = {{ registry = "https://index.example.org/simple" }}

[[package]]
name = "torch"
version = "2.14.0"
source = {{ registry = "https://index.example.org/simple" }}

[[package]]
name = "forked"
version = "1.0"
source = {{ registry = "https://index.example.org/simple" }}
resolution-markers = ["sys_platform == 'darwin'"]

[[package]]
name = "forked"
version = "2.0"
source = {{ registry = "https://index.example.org/simple" }}
resolution-markers = ["sys_platform == 'linux'", "sys_platform == 'win32'"]

[[package]]
name = "unrelated"
version = "1.0"
source = {{ url = "https://example.org/unrelated.tar.gz" }}
"""


def test_the_installed_packages_own_sources_come_from_the_lock(tmp_path):
    """The sources the installed packages declare themselves (uv lock applied them, uv run --with would not): every
    package reachable from the script's dependencies that does not come from an index, a git one at its locked
    commit; extras count only when asked for (not ``ray``), and what is not reachable is left out."""
    s = script(tmp_path, ["linecaster[ray,urlpkg]", "linecaster-kraken"], {
        "linecaster": f'{{ git = "{REPO}", tag = "v0.3.2" }}',
        "linecaster-kraken": f'{{ git = "{REPO}", tag = "v0.3.2", subdirectory = "engines/kraken" }}',
    }, lock=LOCK)
    assert jobs.dependencies("abc123", s).requirements == [
        f"linecaster[urlpkg] @ git+{REPO}@v0.3.2",
        f"linecaster-kraken @ git+{REPO}@v0.3.2#subdirectory=engines/kraken",
        "kraken @ git+https://github.com/storytracer/kraken@48eecb78a8e043b1c658042fcb7c357f68aa786c",
        "urlpkg @ https://example.org/urlpkg.tar.gz",
    ]
    assert jobs.dependencies("abc123", s, engines=False).requirements == [
        f"linecaster[urlpkg] @ git+{REPO}@v0.3.2", "urlpkg @ https://example.org/urlpkg.tar.gz"]


def test_without_a_script():
    assert jobs.dependencies("abc123", engines=False).requirements == [f"linecaster @ {ARCHIVE}"]
    with pytest.raises(PipelineConfigError, match="give the pipeline's script"):
        jobs.dependencies("abc123")


def test_the_locks_index_packages_are_constraints_at_their_versions(tmp_path):
    """Every package the lock takes from an index and the requirements reach is pinned at the lock's version (a
    package held at several versions with its resolution markers); what only Ray reaches is not, nor what nothing
    reaches; without engines only what linecaster reaches."""
    s = script(tmp_path, ["linecaster[ray,urlpkg]", "linecaster-kraken"], {
        "linecaster": f'{{ git = "{REPO}", tag = "v0.3.2" }}',
        "linecaster-kraken": f'{{ git = "{REPO}", tag = "v0.3.2", subdirectory = "engines/kraken" }}',
    }, lock=LOCK)
    assert jobs.dependencies("abc123", s).constraints == [
        "forked==1.0 ; (sys_platform == 'darwin')",
        "forked==2.0 ; (sys_platform == 'linux') or (sys_platform == 'win32')",
        "numpy==2.3.0",
        "torch==2.14.0",
    ]
    assert jobs.dependencies("abc123", s, engines=False).constraints == ["numpy==2.3.0"]
    unlocked = script(tmp_path, ["linecaster"], {"linecaster": f'{{ git = "{REPO}", tag = "v0.3.2" }}'}, name="new.py")
    assert jobs.dependencies("abc123", unlocked).constraints == []          # no lock: nothing to pin


def test_the_scripts_overrides_come_along(tmp_path):
    s = script(tmp_path, ["linecaster", "engine"], {"linecaster": f'{{ git = "{REPO}", tag = "v0.3.2" }}'},
               overrides=["pillow==12.3.0", "tool>=2 ; sys_platform == 'linux'"])
    assert jobs.dependencies("abc123", s).overrides == ["pillow==12.3.0", "tool>=2 ; sys_platform == 'linux'"]


def test_the_launcher_script_carries_requirements_constraints_and_overrides(tmp_path):
    """``Dependencies.script`` is a uv script whose inline metadata holds the three, readable back as written."""
    d = jobs.Dependencies([f"linecaster[urlpkg] @ git+{REPO}@v0.3.2", "stub ; sys_platform == 'linux'"],
                          ["numpy==2.3.0", "forked==1.0 ; (sys_platform == 'darwin')"], ["pillow==12.3.0"])
    path = tmp_path / "launch.py"
    path.write_text(d.script(jobs.LAUNCHER))
    meta = jobs.script_metadata(path)
    assert meta["dependencies"] == d.requirements
    assert meta["tool"]["uv"] == {"constraint-dependencies": d.constraints, "override-dependencies": d.overrides}
    assert path.read_text().endswith(jobs.LAUNCHER)
    plain = tmp_path / "plain.py"
    plain.write_text(jobs.Dependencies(["linecaster"]).script("pass\n"))
    assert jobs.script_metadata(plain) == {"dependencies": ["linecaster"]}


def test_a_derivatives_script_with_a_git_linecaster_needs_no_commit(tmp_path):
    """``--commit`` is unused by a script outside the checkout that takes linecaster from a git tag, branch or rev; it
    stays required without a script, for linecaster's own scripts and for a source that points into the checkout."""
    from linecaster.runtime import run

    s = script(tmp_path, ["linecaster[urlpkg]"], {"linecaster": f'{{ git = "{REPO}", tag = "v0.3.2" }}'})
    assert not jobs.needs_commit(s)
    assert jobs.dependencies(None, s).requirements == [f"linecaster[urlpkg] @ git+{REPO}@v0.3.2"]
    own = jobs.ROOT / "pipelines" / "bind.py"
    assert jobs.needs_commit(own) and jobs.needs_commit(None)
    with pytest.raises(PipelineConfigError, match="--commit"):
        jobs.dependencies(None, own)
    with pytest.raises(PipelineConfigError, match="--commit"):
        jobs.dependencies(None, engines=False)
    into = script(tmp_path, ["linecaster"], {"linecaster": f'{{ path = "{jobs.ROOT}", editable = true }}'}, name="in.py")
    with pytest.raises(PipelineConfigError, match="--commit"):
        jobs.dependencies(None, into)
    a = argparse.Namespace(on="hf-jobs", commit=None)
    run.check_commit(a, str(s))                                            # no error
    with pytest.raises(PipelineConfigError, match="needs --commit"):
        run.check_commit(a, str(own))
    run.check_commit(argparse.Namespace(on="local", commit=None), str(own))


class _Job:
    id, url = "job-1", "https://huggingface.co/jobs/example/job-1"


def test_a_pinned_job_runs_the_launcher_script(monkeypatch):
    """With ``Dependencies`` each Job runs a uv script that carries them (``uv run --with`` would ignore constraints
    and overrides), named like datatrove's own launcher; a list stays datatrove's ``--with`` requirements. The Hub is
    never called: ``run_uv_job`` is replaced."""
    import huggingface_hub

    calls = []

    def run_uv_job(script, script_args=None, dependencies=None, **kwargs):
        calls.append({"name": script.rsplit("/", 1)[-1], "text": open(script).read(), "args": script_args,
                      "dependencies": dependencies, "env": kwargs["env"]})
        return _Job()

    monkeypatch.setattr(huggingface_hub, "run_uv_job", run_uv_job)
    d = jobs.Dependencies([f"linecaster @ {ARCHIVE}"], ["numpy==2.3.0"], ["pillow==12.3.0"])
    kw = dict(tasks=1, logging_dir="memory://linecaster-tests/jobs-launcher", namespace="example", python="3.12")
    pinned = jobs.JobsExecutor([], dependencies=d, **kw)
    assert pinned.dependencies == d.requirements                 # datatrove's attribute: the requirements
    assert pinned._submit_array_index(0, "hf://buckets/example/run/executor.pik", "token") == "job-1"
    call = calls.pop()
    assert call["name"] == "launch_pickled_pipeline.py" and call["dependencies"] is None
    assert call["text"] == d.script(jobs.LAUNCHER) and call["args"] == ["hf://buckets/example/run/executor.pik"]
    assert huggingface_hub.run_uv_job is run_uv_job                 # restored
    plain = jobs.JobsExecutor([], dependencies=[f"linecaster @ {ARCHIVE}"], **kw)
    plain._submit_array_index(0, "hf://buckets/example/run/executor.pik", "token")
    assert calls.pop()["dependencies"] == [f"linecaster @ {ARCHIVE}"]
    unpinned = jobs.JobsExecutor([], dependencies=jobs.Dependencies([f"linecaster @ {ARCHIVE}"]), **kw)
    unpinned._submit_array_index(0, "hf://buckets/example/run/executor.pik", "token")
    assert calls.pop()["dependencies"] == [f"linecaster @ {ARCHIVE}"]   # nothing to pin: datatrove's way


def test_a_commit_is_resolved_to_the_full_sha_the_checkout_knows():
    import subprocess

    from linecaster.runtime.jobs import ROOT, resolve_commit

    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if not head:
        pytest.skip("not a git checkout")
    assert resolve_commit("HEAD") == head and resolve_commit(head[:10]) == head
    assert resolve_commit("0" * 40) == "0" * 40                  # unknown here: as given, GitHub resolves it
