"""The generated documentation: ``linecaster docs`` writes every generated file, when the site is built (they are
not in git).

* ``docs/catalog/``: the catalog's pages (``linecaster.docs.catalog``);
* ``docs/components/``: the component pages (``linecaster.docs.components``);
* ``docs/index.md`` (the README for the site), ``docs/changelog.md``, ``docs/llms.txt`` and ``docs/llms-full.txt``
  (``linecaster.docs.site``).

Generated Markdown pages start with ``HEADER``. The folders ``docs/catalog/<kind>/`` and ``docs/components/`` hold
generated pages only: a page there that a fresh generation does not make is removed.
"""
from __future__ import annotations

from pathlib import Path

from linecaster.catalog import code
from linecaster.docs.common import GITHUB, HEADER, SITE, Links

__all__ = ["GITHUB", "HEADER", "SITE", "Links", "generate", "write"]


def _folders(out: Path) -> list[Path]:
    from linecaster.docs.catalog import KINDS

    return [*(out / "catalog" / k for k in KINDS), out / "components"]


def generate(out: str | Path = "docs", readme: str | Path | None = "README.md", repo: Path | None = code.REPO,
             catalog=None) -> dict[Path, str]:
    """Generates every file: path -> content.

    Args:
        out: the docs folder (``docs``): the catalog's pages go to ``<out>/catalog``, the component pages to
            ``<out>/components``, the site's pages to ``<out>``.
        readme: the README, from which ``index.md`` and ``llms.txt`` are made; ``None`` (or a missing file):
            neither.
        repo: the repository checkout: engines', pipelines' and components' sources, ``CHANGELOG.md``, GitHub links.
        catalog: the catalog (default: linecaster's).
    """
    from linecaster.docs import catalog as catalog_docs
    from linecaster.catalog.registry import Catalog
    from linecaster.docs import components, site

    out = Path(out)
    c = catalog if catalog is not None else Catalog()
    links = Links(out, repo)
    files: dict[Path, str] = {}
    for rel, text in catalog_docs.pages(c, out / "catalog", links, repo).items():
        files[out / "catalog" / rel] = text
    built = components.build(repo)
    for rel, text in components.pages(out / "components", links, c, out / "catalog", repo, built).items():
        files[out / "components" / rel] = text
    readme = Path(readme) if readme is not None else None
    if readme is not None and readme.exists():
        text = readme.read_text(encoding="utf-8")
        files[out / "index.md"] = site.index(text, readme, out, links)
        if repo is not None:
            files[out / "llms.txt"], files[out / "llms-full.txt"] = site.llms(text, out, repo, files)
    if repo is not None and (repo / "CHANGELOG.md").exists():
        files[out / "changelog.md"] = site.changelog((repo / "CHANGELOG.md").read_text(encoding="utf-8"),
                                                      repo / "CHANGELOG.md", out, links)
    return {p: t if t.endswith("\n") else t + "\n" for p, t in files.items()}


def _stale(files: dict[Path, str], out: Path) -> list[Path]:
    """Pages in the generated folders that ``files`` does not hold."""
    made = {p.resolve() for p in files}
    return sorted(p for folder in _folders(out) if folder.is_dir()
                  for p in folder.rglob("*") if p.is_file() and p.resolve() not in made)


def write(files: dict[Path, str], out: str | Path = "docs") -> list[Path]:
    """Writes ``files`` (only those that changed) and removes stale pages from the generated folders; returns the
    paths written or removed."""
    changed = []
    for p in _stale(files, Path(out)):
        p.unlink()
        changed.append(p)
    for folder in _folders(Path(out)):            # folders a removed page left empty
        for d in sorted((d for d in folder.rglob("*") if d.is_dir()), reverse=True) if folder.is_dir() else ():
            if not any(d.iterdir()):
                d.rmdir()
    for p, text in sorted(files.items()):
        if p.exists() and p.read_text(encoding="utf-8") == text:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        changed.append(p)
    return sorted(changed)
