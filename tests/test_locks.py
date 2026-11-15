"""One Ray for every environment: the pin in linecaster's ``ray`` extra, in the project's lock and in each script's."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCKS = sorted([ROOT / "uv.lock", *ROOT.glob("pipelines/*.py.lock"), *ROOT.glob("recipes/*.py.lock")])


def ray_pin() -> str:
    extra = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]["ray"]
    return re.fullmatch(r"ray\[default\]==(\S+)", extra[0]).group(1)


@pytest.mark.parametrize("lock", LOCKS, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_lock_resolves_linecaster_s_ray(lock):
    versions = {p["version"] for p in tomllib.loads(lock.read_text()).get("package", []) if p["name"] == "ray"}
    assert versions <= {ray_pin()}, f"{lock.name}: ray {versions}, linecaster pins {ray_pin()}"
