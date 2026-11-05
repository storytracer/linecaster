"""The self-contained uv scripts (PEP 723: launch.py and those under pipelines/, tools/ and tests/) agree with each other:
the same version pins and kraken source everywhere, a lock next to every script, and wheels for both Linux
machines (aarch64 and x86_64) for every package with compiled wheels. uv's ``required-environments`` does not
work in script metadata, so this test stands in for it."""
import tomllib
from pathlib import Path

import pytest

from linecaster.runtime.jobs import _name, dependencies, script_metadata

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted(p for p in [*ROOT.glob("*.py"), *(q for d in ("pipelines", "tools", "tests") for q in (ROOT / d).rglob("*.py"))]
                 if p.read_text().startswith("# /// script"))
IDS = [p.relative_to(ROOT).as_posix() for p in SCRIPTS]


def lock_of(script: Path) -> dict:
    return tomllib.loads(script.with_name(script.name + ".lock").read_text())


def test_there_are_scripts():
    assert {"launch.py", "pipelines/transcribe_chain.py", "pipelines/transcribe_vlm.py"} <= set(IDS)


def test_launch_finds_the_pipeline():
    """``uv run launch.py NAME ...`` runs the script of the pipeline a recipe or a whole-page model runs in."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("launch", ROOT / "launch.py")
    launch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launch)
    chain, vlm = str(ROOT / "pipelines" / "transcribe_chain.py"), str(ROOT / "pipelines" / "transcribe_vlm.py")
    assert launch.command("squiddle", ["IN", "OUT", "--text", "lines"]) == [
        "uv", "run", "--script", chain, "IN", "OUT", "--text", "lines", "--recipe", "squiddle"]
    assert launch.command("chandra-ocr-2@1", ["IN", "OUT"]) == [
        "uv", "run", "--script", vlm, "IN", "OUT", "--vlm", "chandra-ocr-2@1"]
    assert launch.command("squiddle@1", ["serve", "--port", "8101"]) == [
        "uv", "run", "--script", chain, "serve", "--recipe", "squiddle@1", "--port", "8101"]
    assert launch.command("squiddle", ["ray", "start", "--head"])[-3:] == ["ray", "start", "--head"]
    for name, why in (("nope", "no recipe or model"), ("kraken-ppocrv6-medium", "--recognizer kraken-ppocrv6-medium"),
                      ("minicpm-ocr-1.0", "reads layout regions")):
        with pytest.raises(SystemExit, match=why):
            launch.command(name, ["IN", "OUT"])


@pytest.mark.parametrize("script", SCRIPTS, ids=IDS)
def test_every_script_has_a_lock(script):
    assert script.with_name(script.name + ".lock").exists(), f"uv lock --script {script.relative_to(ROOT)}"


def test_pins_and_kraken_source_agree():
    pins, krakens = {}, set()
    for script in SCRIPTS:
        uv = script_metadata(script).get("tool", {}).get("uv", {})
        for c in uv.get("constraint-dependencies", []):
            pins.setdefault(_name(c), set()).add(c)
        src = uv.get("sources", {}).get("kraken")
        if src:
            krakens.add((src["git"], src["rev"]))
    assert all(len(v) == 1 for v in pins.values()), {k: v for k, v in pins.items() if len(v) > 1}
    assert len(krakens) <= 1, krakens


def test_engine_scripts_share_one_pin_list():
    lists = {tuple(script_metadata(s).get("tool", {}).get("uv", {}).get("constraint-dependencies", []))
             for s in SCRIPTS if any(_name(d).startswith("linecaster-") for d in script_metadata(s)["dependencies"])}
    assert len(lists) == 1, lists


@pytest.mark.parametrize("script", SCRIPTS, ids=IDS)
def test_lock_resolves_the_pins(script):
    versions = {p["name"]: p.get("version") for p in lock_of(script)["package"]}
    for c in script_metadata(script).get("tool", {}).get("uv", {}).get("constraint-dependencies", []):
        name, _, version = c.partition("==")
        if name in versions:
            assert versions[name] == version, (name, versions[name], version)


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
    chain, vlm = ROOT / "pipelines/transcribe_chain.py", ROOT / "pipelines/transcribe_vlm.py"
    for script in (chain, vlm):
        deps = dependencies("abc123", script)
        assert deps[0] == "linecaster[pybookget] @ https://github.com/storytracer/linecaster/archive/abc123.tar.gz"
        assert "pybookget @ https://github.com/storytracer/pybookget/archive/449bcc50b25aaa8d4ad4ea00bc78c9554e136af7.tar.gz" in deps                       # an archive, no git (the vLLM image has none)
        assert not any(" @ ." in d or "path" in d for d in deps)
    assert "kraken @ git+https://github.com/storytracer/kraken@48eecb78" in dependencies("abc123", chain)
    assert not any(_name(d) in ("lightning", "torch", "kraken") for d in dependencies("abc123", vlm))
    # without engines: linecaster with its extras and the archive-source packages, no engines, no pins
    assert dependencies("abc123", vlm, engines=False) == [
        "linecaster[pybookget] @ https://github.com/storytracer/linecaster/archive/abc123.tar.gz",
        "pybookget @ https://github.com/storytracer/pybookget/archive/449bcc50b25aaa8d4ad4ea00bc78c9554e136af7.tar.gz"]


def test_serve_command_for_a_pipeline():
    from linecaster.serve import serve_command

    cmd = serve_command([{"name": "layout", "spec": "x:Y"}], 8101, script="pipelines/transcribe_chain.py")
    assert cmd[:6] == ["uv", "run", "--quiet", "--script", "pipelines/transcribe_chain.py", "serve"]
    assert cmd[6:10] == ["--port", "8101", "--max-queue", "16"]
