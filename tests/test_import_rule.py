"""The import rules. The data model, the formats, the text transforms, the image helpers and the built-in rule-based
engines and the scorer (every module of ``linecaster.data``, ``linecaster.formats``, ``linecaster.text``,
``linecaster.images``, ``linecaster.engines`` and ``linecaster.scoring``) load neither datatrove nor saturate, nor linecaster's blocks or runtime; checked in a fresh
interpreter, so nothing another test imported counts. The engine packages (``engines/*``) import from linecaster
only the data model and the engine API (``linecaster.engines.api``), read with ``ast``."""
import ast
import json
import subprocess
import sys
from pathlib import Path

LIGHT = ("linecaster.data", "linecaster.formats", "linecaster.text", "linecaster.images", "linecaster.engines",
         "linecaster.scoring")
HEAVY = ("datatrove", "saturate", "linecaster.blocks", "linecaster.runtime")

CHECK = f"""
import importlib, json, pkgutil, sys
for name in {LIGHT!r}:
    pkg = importlib.import_module(name)
    for m in pkgutil.walk_packages(pkg.__path__, name + "."):
        importlib.import_module(m.name)
heavy = {HEAVY!r}
print(json.dumps(sorted(m for m in sys.modules if any(m == h or m.startswith(h + ".") for h in heavy))))
"""


def test_light_packages_do_not_load_the_pipeline_machinery():
    out = subprocess.run([sys.executable, "-c", CHECK], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == []


# ------------------------------------------------------------------------------------- the engine packages
ROOT = Path(__file__).resolve().parents[1]
#: what an engine package may import from linecaster: the data model and the engine API
ENGINE_API = ("linecaster.data", "linecaster.engines.api")


def linecaster_imports(path: Path) -> list[tuple[int, str]]:
    """Every ``linecaster`` module a file imports (at any depth), with its line."""
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name) for a in node.names if a.name.split(".")[0] == "linecaster"]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "linecaster":
            out += [(node.lineno, node.module)] if node.module != "linecaster" else [
                (node.lineno, f"linecaster.{a.name}") for a in node.names]
    return out


def test_engine_packages_use_only_the_engine_api():
    files = sorted(ROOT.glob("engines/*/src/**/*.py")) + sorted(ROOT.glob("engines/*/tests/**/*.py"))
    assert files
    allowed = (*ENGINE_API, "linecaster.testing")       # an engine's tests may use the test helpers too
    offenders = []
    for f in files:
        ok = ENGINE_API if "/src/" in f.as_posix() else allowed
        offenders += [f"{f.relative_to(ROOT)}:{line}: {m}" for line, m in linecaster_imports(f)
                      if not any(m == a or m.startswith(a + ".") for a in ok)]
    assert offenders == []


def test_the_rule_finds_an_internal_import(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("from linecaster.catalog.fetch import hf_file\nimport linecaster.data\n"
                 "def g():\n    from linecaster import runtime\n")
    assert linecaster_imports(f) == [(1, "linecaster.catalog.fetch"), (2, "linecaster.data"), (4, "linecaster.runtime")]
