"""The self-contained uv scripts (PEP 723) under servers/, examples/, recipes/ and tests/ agree with each other:
the same version pins and kraken source everywhere, a lock next to every script, and wheels for both Linux
machines (aarch64 and x86_64) for every package with compiled wheels. uv's ``required-environments`` does not
work in script metadata, so this test stands in for it."""
import tomllib
from pathlib import Path

import pytest

from linecaster.jobs import SERVERS, _name, dependencies, script_metadata

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted(p for d in ("servers", "examples", "recipes", "tests") for p in (ROOT / d).rglob("*.py")
                 if p.read_text().startswith("# /// script"))
IDS = [p.relative_to(ROOT).as_posix() for p in SCRIPTS]


def lock_of(script: Path) -> dict:
    return tomllib.loads(script.with_name(script.name + ".lock").read_text())


def test_there_are_scripts():
    assert {"servers/kraken-paddlex.py", "servers/paddlex-tesseract.py", "examples/squiddle_chain.py"} <= set(IDS)


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


def test_server_scripts_feed_the_jobs_helper():
    for engines in ("kraken-paddlex", "paddlex-tesseract"):
        assert (SERVERS / f"{engines}.py").exists()
        deps = dependencies("abc123", engines)
        assert deps[0] == "linecaster @ https://github.com/storytracer/linecaster/archive/abc123.tar.gz"
        assert not any(" @ ." in d or "path" in d for d in deps)
    assert not any(_name(d) in ("lightning", "torch") for d in dependencies("abc123", "paddlex-tesseract"))


def test_serve_command_for_a_server_script():
    from linecaster.serve import serve_command

    cmd = serve_command([{"name": "layout", "spec": "x:Y"}], 8101, script="servers/kraken-paddlex.py")
    assert cmd[:5] == ["uv", "run", "--quiet", "--script", "servers/kraken-paddlex.py"]
    assert cmd[5:9] == ["--port", "8101", "--max-queue", "16"]
