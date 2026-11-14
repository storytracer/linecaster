"""MediaWiki's TeX checker, texvc, as the reader runs it: texvcjs (Wikimedia's JavaScript texvc, npm
``mathoid-texvcjs``, GPL-2.0; pinned by ``texvc/package-lock.json``), installed into a site folder by
``linecaster-mediawiki intake`` (``install``) and run in Node, one process per reading process.

``Texvc.check`` gives a formula as texvc writes it: MediaWiki's own commands as standard LaTeX (``\\R`` ->
``\\mathbb {R}``, ``\\Mu`` -> ``\\mathrm {M}``, ``\\and`` -> ``\\land``), ``align`` as ``aligned``, every argument in
braces (``\\overline\\frac{a}{b}`` -> ``{\\overline {\\frac {a}{b}}}``) -- LaTeX that LaTeX and KaTeX read -- or None
where texvc rejects it. A site taken in without it reads formulas as written.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

PACKAGE = Path(__file__).parent / "texvc"
FILES = ("package.json", "package-lock.json", "check.js")
#: what a reading records it ran
VERSION = "mathoid-texvcjs " + json.loads((PACKAGE / "package.json").read_text())["dependencies"]["mathoid-texvcjs"]


def install(folder: Path) -> Path:
    """texvcjs into ``folder/texvc`` at the pinned version (``npm ci``: the package registry is read here, at intake,
    never while reading)."""
    target = folder / "texvc"
    target.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        shutil.copy(PACKAGE / f, target / f)
    subprocess.run(["npm", "ci", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund", "--loglevel=error"],
                   cwd=target, check=True)
    return target


class Texvc:
    """texvc for one site folder, its answers kept (a formula repeats across an item's pages)."""

    def __init__(self, folder: Path):
        self.script = Path(folder) / "texvc" / "check.js"
        self._proc: subprocess.Popen | None = None
        self._answers: dict[str, str | None] = {}

    @property
    def installed(self) -> bool:
        return (self.script.parent / "node_modules" / "mathoid-texvcjs").is_dir()

    def check(self, tex: str) -> str | None:
        """``tex`` as texvc writes it, or None where texvc rejects it."""
        if tex not in self._answers:
            if self._proc is None or self._proc.poll() is not None:
                self._proc = subprocess.Popen(["node", str(self.script)], stdin=subprocess.PIPE,
                                              stdout=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
            self._proc.stdin.write(json.dumps(tex) + "\n")
            self._proc.stdin.flush()
            self._answers[tex] = json.loads(self._proc.stdout.readline())["output"]
        return self._answers[tex]
