"""The self-contained uv scripts (PEP 723: launch.py and those under pipelines/, tools/ and tests/) agree with each other:
the same kraken source everywhere, a lock next to every script, and wheels for both Linux
machines (aarch64 and x86_64) for every package with compiled wheels. uv's ``required-environments`` does not
work in script metadata, so this test stands in for it."""
import tomllib
from pathlib import Path

import pytest

from linecaster.runtime.jobs import _name, dependencies, script_metadata

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted(p for p in [*ROOT.glob("*.py"), *(q for d in ("pipelines", "recipes", "tools", "tests") for q in (ROOT / d).rglob("*.py"))]
                 if p.read_text().startswith("# /// script"))
IDS = [p.relative_to(ROOT).as_posix() for p in SCRIPTS]


def lock_of(script: Path) -> dict:
    return tomllib.loads(script.with_name(script.name + ".lock").read_text())


def test_there_are_scripts():
    assert {"launch.py", "pipelines/transcribe_modular.py", "pipelines/transcribe_vlm.py",
            "pipelines/transcribe_page.py"} <= set(IDS)


def test_every_pipeline_script_has_its_id():
    """A pipeline's id is its script's name plus ``.v<n>`` (``PIPELINE``); the docs have a page for each."""
    import re

    from linecaster.catalog import code

    found = {pl.source.name: pid for pid, pl in code.pipelines(ROOT).items()}
    assert set(found) == {p.name for p in (ROOT / "pipelines").glob("*.py")}
    assert all(re.fullmatch(rf"{name[:-3]}\.v\d+", pid) for name, pid in found.items())


def test_every_pipeline_script_runs_its_shape():
    """A pipeline script is an environment and a command line: it imports the pipeline shape of its own name
    (``linecaster.pipelines.<name>``) and defines nothing itself."""
    import ast

    for script in sorted((ROOT / "pipelines").glob("*.py")):
        tree = ast.parse(script.read_text(encoding="utf-8"))
        shapes = [(a.name, a.asname) for n in tree.body if isinstance(n, ast.ImportFrom)
                  and n.module == "linecaster.pipelines" for a in n.names]
        assert shapes == [(script.stem, "shape")], script.name
        assert not [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Assign))], script.name


RECIPES = sorted((ROOT / "recipes").glob("*.py"))
LINECASTER = "https://github.com/storytracer/linecaster"


def test_every_recipe_has_its_script():
    """Every catalog recipe has ``recipes/<id>.py`` (its environment and entry point), and every recipe script is a
    recipe's."""
    from linecaster.catalog.registry import catalog

    assert {p.stem for p in RECIPES} == set(catalog().recipes)


@pytest.mark.parametrize("script", RECIPES, ids=[p.stem for p in RECIPES])
def test_a_recipe_script_lists_exactly_its_engine_packages(script):
    """A recipe script's dependencies are ``linecaster[ray]`` and exactly the engine packages its presets need (recipe
    -> presets -> engines -> packages: ``code.recipe_packages``), each from linecaster's ``main`` on GitHub, so the
    script runs from its URL as well as from a checkout; its body only calls ``run.recipe`` with its own id."""
    import ast

    from linecaster.catalog import code

    meta = script_metadata(script)
    deps = meta["dependencies"]
    assert "linecaster[ray]" in deps, script.name
    assert {_name(d) for d in deps} - {"linecaster"} == code.recipe_packages(script.stem), script.name
    sources = meta["tool"]["uv"]["sources"]
    assert set(sources) == {_name(d) for d in deps}, script.name
    for name, source in sources.items():
        assert source.get("git") == LINECASTER and source.get("branch") == "main" and "path" not in source, name
        assert source.get("subdirectory") == (None if name == "linecaster" else f"engines/{name.removeprefix('linecaster-')}")
    tree = ast.parse(script.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "recipe"]
    assert len(calls) == 1 and calls[0].args[1].value == script.stem, script.name
    assert not [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Assign))], script.name


@pytest.mark.parametrize("script", RECIPES, ids=[p.stem for p in RECIPES])
def test_a_recipe_scripts_lock_is_current(script):
    """A recipe script's lock holds what its header lists now (``uv lock --script --check``); the commit of
    linecaster's ``main`` it was locked at may be older (relock with ``--upgrade-package`` for linecaster's packages
    to move it)."""
    import subprocess

    r = subprocess.run(["uv", "lock", "--script", str(script), "--check", "--offline"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_launch_finds_the_pipeline():
    """``uv run launch.py NAME ...`` runs the script of the pipeline a recipe or a page preset runs in."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("launch", ROOT / "launch.py")
    launch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launch)
    squiddle, vlm = str(ROOT / "recipes" / "squiddle.py"), str(ROOT / "pipelines" / "transcribe_vlm.py")
    assert launch.command("squiddle", ["IN", "OUT", "--furniture"]) == [
        "uv", "run", "--script", squiddle, "IN", "OUT", "--furniture", "--recipe", "squiddle"]
    texts = str(ROOT / "recipes" / "item-texts.py")
    assert launch.command("item-texts", ["P", "OUT"]) == ["uv", "run", "--script", texts, "P", "OUT", "--recipe",
                                                          "item-texts"]
    assert launch.command("chandra-ocr-2@1", ["IN", "OUT"]) == [
        "uv", "run", "--script", vlm, "IN", "OUT", "--recognition", "chandra-ocr-2@1"]
    page = str(ROOT / "pipelines" / "transcribe_page.py")
    assert launch.command("indra-ocr@1", ["IN", "OUT"]) == [
        "uv", "run", "--script", page, "IN", "OUT", "--recognition", "indra-ocr@1"]
    assert launch.command("falcon-ocr", ["serve"])[4:6] == ["serve", "--recognition"]   # a page engine can be served
    assert launch.command("squiddle@1", ["serve", "--port", "8101"]) == [
        "uv", "run", "--script", squiddle, "serve", "--recipe", "squiddle@1", "--port", "8101"]
    assert launch.command("squiddle", ["ray", "start", "--head"])[-3:] == ["ray", "start", "--head"]
    for name, why in (("nope", "no recipe or page preset"), ("kraken-ppocrv6-medium", "--recognition kraken-ppocrv6-medium"),
                      ("minicpm-ocr-1.0", "reads layout regions")):
        with pytest.raises(SystemExit, match=why):
            launch.command(name, ["IN", "OUT"])


@pytest.mark.parametrize("script", SCRIPTS, ids=IDS)
def test_every_script_has_a_lock(script):
    assert script.with_name(script.name + ".lock").exists(), f"uv lock --script {script.relative_to(ROOT)}"


def test_kraken_source_agrees():
    """The kraken fork is declared once, by linecaster-kraken; a script that names it too names the same."""
    krakens = {(s["git"], s["rev"]) for s in [
        tomllib.loads((ROOT / "engines/kraken/pyproject.toml").read_text())["tool"]["uv"]["sources"]["kraken"],
        *(script_metadata(p).get("tool", {}).get("uv", {}).get("sources", {}).get("kraken") for p in SCRIPTS)] if s}
    assert len(krakens) == 1, krakens


def test_scripts_list_no_source_their_packages_bring():
    """A script lists only what it needs itself: the kraken fork and the OpenCV stub come with the packages that
    need them (linecaster, linecaster-kraken, linecaster-paddlex declare their sources, which uv lock applies)."""
    for p in SCRIPTS:
        names = {_name(d) for d in script_metadata(p).get("dependencies", [])}
        assert not names & {"kraken", "opencv-contrib-python", "s3fs"}, p.name


def test_s3_comes_with_the_core():
    """``s3://`` needs no extra: the core installs datatrove's ``s3`` extra (s3fs), linecaster has no ``s3fs`` extra,
    and every pipeline script's lock has s3fs."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert any(d.startswith("datatrove[io,s3]") for d in project["dependencies"])
    assert "s3fs" not in project["optional-dependencies"]
    for p in SCRIPTS:
        assert not any(_name(d) == "linecaster" and "s3fs" in d for d in script_metadata(p).get("dependencies", [])), p
    for p in sorted((ROOT / "pipelines").glob("*.py")):
        assert "s3fs" in {q["name"] for q in lock_of(p)["package"]}, p.name


#: the torch each script's lock holds, and why. Only linecaster-kraken pins torch (2.14.0, kraken's upper bound), and
#: only environments with linecaster-kraken are bound by it; the others take what their own dependencies allow. A lock
#: whose torch changes fails here: a change of build is deliberate and recorded in NOTES.md
TORCH = {
    "tests/test_engines_catalog.py": ("2.14.0", "linecaster-kraken's pin"),
    "recipes/squiddle.py": ("2.14.0", "linecaster-kraken's pin"),
    "pipelines/transcribe_page.py": ("2.14.0", "surya-ocr's (>=2.7,<3), not pinned; the version it was locked at"),
    "tests/test_page_engines_catalog.py": ("2.14.0", "surya-ocr's (>=2.7,<3), not pinned; the version it was locked at"),
    "tools/cuda_probe.py": ("2.14.0", "it probes the CUDA build of linecaster-kraken's torch on a Jobs host"),
}


def test_only_linecaster_kraken_pins_torch():
    """No pyproject but linecaster-kraken's names torch (the core never depends on it, nor does another engine)."""
    for pyproject in sorted([ROOT / "pyproject.toml", *ROOT.glob("engines/*/pyproject.toml"),
                             *ROOT.glob("stubs/*/pyproject.toml")]):
        project = tomllib.loads(pyproject.read_text())["project"]
        reqs = [*project.get("dependencies", []), *(r for rs in project.get("optional-dependencies", {}).values()
                                                     for r in rs)]
        torch = [r for r in reqs if _name(r) == "torch"]
        rel = pyproject.relative_to(ROOT).as_posix()
        assert torch == (["torch==2.14.0"] if rel == "engines/kraken/pyproject.toml" else []), rel


@pytest.mark.parametrize("script", SCRIPTS, ids=IDS)
def test_torch_per_environment(script):
    """A lock has torch only as ``TORCH`` says; one with linecaster-kraken has its 2.14.0, and one without says why
    it has torch at all."""
    rel = script.relative_to(ROOT).as_posix()
    names = {p["name"]: p.get("version") for p in lock_of(script)["package"]}
    assert names.get("torch") == TORCH.get(rel, (None,))[0], f"{rel}: torch {names.get('torch')}; update TORCH"
    if "linecaster-kraken" in names:
        assert TORCH[rel] == ("2.14.0", "linecaster-kraken's pin"), rel
    elif rel in TORCH:
        assert "kraken's pin" not in TORCH[rel][1], rel


#: packages allowed to build from source on one machine, and why that cannot move numerics
SOURCE_BUILDS = {
    # kraken's CoreML format (the blla .mlmodel); no Linux aarch64 wheel; not on the recognition path
    "coremltools": "aarch64",
}


@pytest.mark.parametrize("script", SCRIPTS, ids=IDS)
def test_wheels_for_both_machines(script):
    """Every package with platform wheels has a Linux wheel for aarch64 and for x86_64 (a source build on
    one machine would make its numerics differ), unless the lock installs it on one platform only."""
    lock = lock_of(script)
    only_some = {d["name"] for q in lock["package"] for d in q.get("dependencies", [])
                 if "platform_machine" in d.get("marker", "") or "sys_platform" in d.get("marker", "")}
    missing = []
    for p in lock["package"]:
        wheels = [w["url"].rsplit("/", 1)[-1] for w in p.get("wheels", [])]
        if not wheels or any(w.endswith("-none-any.whl") for w in wheels) or p["name"] in only_some:
            continue
        missing += [f"{p['name']} {p.get('version')}: {arch}" for arch in ("aarch64", "x86_64")
                    if not any("linux" in w and arch in w for w in wheels) and SOURCE_BUILDS.get(p["name"]) != arch]
    assert missing == []


def test_pipelines_feed_the_jobs_helper():
    """A Job installs linecaster and the engine packages from the archive at the commit, and the sources the packages
    declare themselves from the script's lock: the OpenCV stub. linecaster's own requirement keeps the script's extras
    but ``ray``, which a Job leaves out: ``nvimgcodec`` decodes the pages on the Job's GPU."""
    modular, vlm = ROOT / "pipelines/transcribe_modular.py", ROOT / "pipelines/transcribe_vlm.py"
    repo = "https://github.com/storytracer/linecaster/archive/abc123.tar.gz"
    for script in (modular, vlm):
        deps = dependencies("abc123", script).requirements
        assert deps[0] == f"linecaster[nvimgcodec] @ {repo}"   # an archive, no git (the vLLM image has none)
        assert f"opencv-contrib-python @ {repo}#subdirectory=stubs/opencv-contrib-python" in deps
        assert not any(" @ ." in d or "path" in d for d in deps)
    for script in (modular, vlm):                   # kraken runs in an environment that adds it, not in these
        d = dependencies("abc123", script)
        assert not any(_name(r) in ("lightning", "torch", "kraken", "linecaster-kraken")
                       for r in d.requirements + d.constraints)
    # without engines: linecaster alone, no engines
    assert dependencies("abc123", vlm, engines=False).requirements == [f"linecaster[nvimgcodec] @ {repo}"]


@pytest.mark.parametrize("script", sorted((ROOT / "pipelines").glob("*.py")), ids=lambda p: p.name)
def test_jobs_resolve_the_locks_versions(script):
    """A Job of every pipeline script is pinned to its lock: each package the lock takes from an index and the
    requirements reach is a constraint at the lock's version, nothing else is, and the script's overrides come
    along (transcribe_page.py's pillow, without which its lock does not resolve)."""
    lock = lock_of(script)
    registry = {p["name"]: p["version"] for p in lock["package"] if "registry" in p.get("source", {})}
    d = dependencies("abc123", script)
    pins = dict(c.split("==", 1) for c in d.constraints)
    assert pins and all(registry[n] == v for n, v in pins.items())
    assert not pins.keys() & {_name(r) for r in d.requirements}           # a requirement with a URL is no pin
    assert d.overrides == script_metadata(script).get("tool", {}).get("uv", {}).get("override-dependencies", [])
    assert pins.get("torch") == TORCH.get(script.relative_to(ROOT).as_posix(), (None,))[0]   # the lock's torch
    if script.name == "transcribe_page.py":
        assert d.overrides == ["pillow==12.3.0"] and pins["pillow"] == "12.3.0"


def test_serve_command_for_a_pipeline():
    from linecaster.serve import serve_command

    cmd = serve_command([{"name": "layout", "spec": "x:Y"}], 8101, script="pipelines/transcribe_modular.py")
    assert cmd[:6] == ["uv", "run", "--quiet", "--script", "pipelines/transcribe_modular.py", "serve"]
    assert cmd[6:10] == ["--port", "8101", "--max-queue", "16"]
