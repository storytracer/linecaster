"""The import rule: the data model, the formats, the text transforms and the image helpers (every module of
``linecaster.data``, ``linecaster.formats``, ``linecaster.text`` and ``linecaster.images``) load neither
datatrove nor saturate, nor linecaster's blocks or runtime. Checked in a fresh interpreter, so nothing another
test imported counts."""
import json
import subprocess
import sys

LIGHT = ("linecaster.data", "linecaster.formats", "linecaster.text", "linecaster.images")
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
