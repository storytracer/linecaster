"""Every field of ``linecaster.page/2`` (its frozen JSON Schema, ``tests/schemas/page-2.json``) has a row in the data
model's table "From ``linecaster.page/2``", so the upgrade to page/3 accounts for each one."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "tests" / "schemas" / "page-2.json"
SPEC = ROOT / "docs" / "reference" / "data-model.md"


def _fields() -> set[str]:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    out = {f"Page.{name}" for name in schema["properties"]}
    for cls, d in schema["$defs"].items():
        out |= {f"{cls}.{name}" for name in d.get("properties", {})}
    return out


def _mapped() -> set[str]:
    section = SPEC.read_text(encoding="utf-8").split("## From `linecaster.page/2`", 1)[1]
    out = set()
    for row in re.findall(r"^\| (.+?) \| .+ \|$", section, flags=re.M):
        cls = None
        for name in re.findall(r"`([^`]+)`", row):
            name = re.sub(r"\[.*\]$", "", name)
            if "." in name:
                cls, name = name.split(".", 1)
            if cls:
                out.add(f"{cls}.{name}")
    return out


def test_every_page_2_field_has_a_row_in_the_field_map():
    missing = _fields() - _mapped()
    assert not missing, sorted(missing)
