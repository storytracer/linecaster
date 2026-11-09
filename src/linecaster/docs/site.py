"""The site's own generated pages (``linecaster docs``): ``docs/index.md`` from the README and ``docs/changelog.md``
from ``CHANGELOG.md``, their links rewritten for the site, and ``docs/llms.txt`` / ``docs/llms-full.txt``
(llmstxt.org), which the site serves at its root."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import regex

from .common import GITHUB, HEADER, SITE, Links

#: the raw Markdown of the repository's files, for llms.txt
RAW = "https://raw.githubusercontent.com/storytracer/linecaster/main"
#: the hand-written reference pages in the order the site and llms-full.txt give them; others follow by name
REFERENCE = ("glossary", "conventions", "architecture", "pipelines", "data-model", "serialization", "catalog",
             "tracing", "compatibility")
ALERTS = {"NOTE": "note", "TIP": "tip", "IMPORTANT": "info", "WARNING": "warning", "CAUTION": "danger"}

LINK = re.compile(r"(\]\()([^)\s]+)(\))")
SRC = re.compile(r'((?:src|href)=")([^"]+)(")')
DEFINITION = re.compile(r"^(\[[^\]]+\]:\s*)(\S+)()", re.M)


def github_slug(heading: str) -> str:
    """GitHub's anchor of a heading: lower case, punctuation and symbols removed, spaces as hyphens."""
    return regex.sub(r"[^\p{L}\p{M}\p{N}\p{Pc}\- ]", "", heading.lower()).replace(" ", "-")


def site_slug(heading: str) -> str:
    """The site's anchor of a heading: Python-Markdown's ``toc`` slug (ASCII, hyphens)."""
    value = unicodedata.normalize("NFKD", heading).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value)


def _heading_text(line: str) -> str:
    text = line.lstrip("#").strip()
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return text.replace("`", "").replace("*", "")


def anchors(text: str) -> dict[str, str]:
    """GitHub anchor -> site anchor, for every heading of ``text`` outside code blocks."""
    out, fenced = {}, False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and re.match(r"#{1,6} ", line):
            h = _heading_text(line)
            out[github_slug(h)] = site_slug(h)
    return out


def _target(target: str, source: Path, page_dir: Path, links: Links, slugs: dict[str, str]) -> str:
    if re.match(r"[a-z][a-z0-9+.-]*:", target):              # http:, https:, mailto:
        return target
    if target.startswith("#"):
        from urllib.parse import unquote

        name = unquote(target[1:])
        return "#" + slugs.get(name, name)
    path, _, fragment = target.partition("#")
    out = links.to(source.parent / path, page_dir)
    return out + (f"#{fragment}" if fragment else "")


def rewrite_links(text: str, source: Path, page: Path, links: Links) -> str:
    """``text`` (the file ``source``) with its links rewritten for the page ``page``: relative within the docs, to
    GitHub for the rest of the repository, in-page anchors as the site makes them."""
    slugs = anchors(text)
    fix = lambda m: m.group(1) + _target(m.group(2), source, page.parent, links, slugs) + m.group(3)  # noqa: E731
    out, fenced = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        if not fenced:
            line = DEFINITION.sub(fix, SRC.sub(fix, LINK.sub(fix, line)))
        out.append(line)
    return "\n".join(out)


def admonitions(text: str) -> str:
    """GitHub's alerts (``> [!NOTE]``) as the site's admonitions (``!!! note``)."""
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        m = re.match(r"> \[!(\w+)\]\s*$", lines[i])
        if m and m.group(1) in ALERTS:
            out += [f"!!! {ALERTS[m.group(1)]}", ""]
            i += 1
            while i < len(lines) and lines[i].startswith(">"):
                out.append(("    " + lines[i][1:].lstrip()).rstrip())
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def index(readme_text: str, readme: Path, out: Path, links: Links) -> str:
    """``docs/index.md``: the README for the site: links rewritten, alerts as admonitions, Markdown inside
    ``<details>`` rendered."""
    text = rewrite_links(readme_text, readme, out / "index.md", links)
    text = admonitions(text).replace("<details>", '<details markdown="1">')
    return f"{HEADER}\n{text.rstrip()}\n"


def changelog(text: str, source: Path, out: Path, links: Links) -> str:
    """``docs/changelog.md``: ``CHANGELOG.md`` with its links rewritten for the site."""
    return f"{HEADER}\n{rewrite_links(text, source, out / 'changelog.md', links).rstrip()}\n"


def _strip_header(text: str) -> str:
    return text.split("\n", 1)[1] if text.startswith("<!-- Generated") else text


def _title_and_summary(text: str) -> tuple[str, str]:
    lines = _strip_header(text).splitlines()
    title = next((ln.lstrip("# ").strip() for ln in lines if ln.startswith("# ")), "")
    para, started = [], False
    for ln in lines:
        if ln.startswith("#") or ln.startswith("```") or ln.startswith("|") or ln.startswith("<"):
            if started:
                break
            continue
        if not ln.strip():
            if started:
                break
            continue
        started = True
        para.append(ln.strip())
    first = re.split(r"(?<=[.:])\s", " ".join(para), maxsplit=1)[0]
    return title, re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", first).rstrip(":.") + "."


def reference_pages(out: Path) -> list[Path]:
    found = {p.stem: p for p in sorted((out / "reference").glob("*.md"))}
    return [found[n] for n in REFERENCE if n in found] + [p for n, p in found.items() if n not in REFERENCE]


def llms(readme_text: str, out: Path, repo: Path, generated: dict[Path, str]) -> tuple[str, str]:
    """``llms.txt`` (title, summary, sections of links to the pages' Markdown) and ``llms-full.txt`` (the README, the
    reference pages, the block index and the catalog index, concatenated)."""
    def text_of(p: Path) -> str:
        return generated[p] if p in generated else p.read_text(encoding="utf-8")

    def rel(p: Path) -> str:
        p = p.resolve()
        return p.relative_to(repo.resolve()).as_posix() if p.is_relative_to(repo.resolve()) else p.as_posix()

    def raw(p: Path) -> str:
        return f"{RAW}/{rel(p)}"

    readme = repo / "README.md"
    tagline = next((ln.lstrip("# ").strip() for ln in readme_text.splitlines() if ln.startswith("### ")), "")
    ref = reference_pages(out)
    lines = ["# Linecaster", "", f"> {tagline}: text recognition (OCR and HTR) for print and handwriting, with "
             "layout, line, text, table and formula recognizers and post-processing as blocks of datatrove "
             "pipelines that run in-process or against model servers, on a laptop, a cluster or Hugging Face Jobs.",
             "", "Every model configuration is a catalog preset at a pinned revision; tested combinations are recipes. "
             "The pages below are Markdown, except the generated Blocks and Catalog, which are the site's pages "
             "(llms-full.txt holds their indexes).", "", "## Start", "",
             f"- [README]({raw(readme)}): why, quick start, how it works, running anywhere, outputs", "",
             "## Reference", ""]
    for p in ref:
        title, summary = _title_and_summary(text_of(p))
        lines.append(f"- [{title}]({raw(p)}): {summary}")
    lines += ["", "## Generated", "",
              f"- [Blocks]({SITE}/blocks/): every block by family, with a page each "
              "(contract, backends, options, behavior)",
              f"- [Catalog]({SITE}/catalog/): engines, models, presets, pipelines and recipes, "
              "with a page each and their evidence", "", "## Optional", "",
              f"- [Changelog]({raw(repo / 'CHANGELOG.md')}): upgrade notes and changes",
              f"- [Repository]({GITHUB.rsplit('/blob/', 1)[0]}): the source", ""]
    full = []
    for p in [readme, *ref, out / "blocks" / "README.md", out / "catalog" / "README.md"]:
        body = readme_text if p == readme else text_of(p)
        full += [f"<!-- {rel(p)} -->", "",
                 _strip_header(body).strip(), ""]
    return "\n".join(lines), "\n".join(full)
