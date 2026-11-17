"""Moves imports written for linecaster 0.12 to the modules' places in 0.13.

    python tools/codemod_0_13.py PATH [PATH ...]        # rewrites the .py, .md, .yaml, .yml and .toml files below
    python tools/codemod_0_13.py --dry-run PATH         # lists the files it would change

Code written for 0.11 goes through ``tools/codemod_0_12.py`` first.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codemod_0_12 as base  # noqa: E402

#: modules, old dotted path -> new one; the longer paths first
MODULES: list[tuple[str, str]] = [
    ("linecaster.engines.paragraphs.rules", "linecaster.text.paragraphs"),
    ("linecaster.engines.hierarchy.rules", "linecaster.text.hierarchy"),
    ("linecaster.engines.paragraphs.engine", "linecaster.engines.paragraphs"),
    ("linecaster.engines.hierarchy.engine", "linecaster.engines.hierarchy"),
    ("linecaster.execution.secrets", "linecaster.secrets"),
    ("linecaster.execution.observers", "linecaster.core.observers"),
    ("linecaster.catalog.docs", "linecaster.docs.catalog"),
    ("linecaster.catalog.formats", "linecaster.schemas"),
    ("linecaster.formats.omnidocbench", "linecaster.evaluation.omnidocbench"),
]


def rewrite(text: str, python: bool) -> str:
    base.MODULES = MODULES
    if python:
        text = base._module_imports(text)
    return base._modules(text)


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print(__doc__)
        return 2
    for p in base.files(paths):
        if p.name == "codemod_0_13.py":
            continue
        try:
            old = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new = rewrite(old, p.suffix == ".py")
        if new != old:
            print(p)
            if not dry:
                p.write_text(new, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
