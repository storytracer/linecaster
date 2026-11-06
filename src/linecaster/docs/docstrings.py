"""Google-style docstrings, read for the generated docs and checked by ``tests/test_docstrings.py``
(``docs/reference/conventions.md``, "Docstrings").

A docstring is a summary (its first paragraph), a body, and sections: ``Args:`` (one entry per parameter, ``name:
description``; several names may share an entry, ``a, b, c: description``; continuation lines are indented),
``Example:`` (indented Python code), and others (``Returns:``, ``Raises:``, ``Note:``), which stay in the body.
"""
from __future__ import annotations

import inspect
import re
import textwrap
from dataclasses import dataclass, field

#: section headers, each on a line of its own at the docstring's indentation
SECTION = re.compile(r"^(Args|Arguments|Example|Examples|Returns|Yields|Raises|Note|Notes):\s*$")
#: the start of an ``Args:`` entry: one or more names (``*args``, ``**kwargs`` allowed), an optional type in parentheses
ENTRY = re.compile(r"^(\*{0,2}\w+(?:\s*,\s*\*{0,2}\w+)*)\s*(?:\([^)]*\))?\s*:\s*(.*)$")


@dataclass
class Docstring:
    summary: str = ""
    body: str = ""
    args: dict[str, str] = field(default_factory=dict)
    example: str = ""
    #: problems found while reading it (an ``Args:`` line that is no entry)
    problems: list[str] = field(default_factory=list)


def parse(text: str | None) -> Docstring:
    """Reads a docstring into its summary, body, ``Args:`` entries and ``Example:``.

    Args:
        text: the docstring as written (indentation is removed); ``None`` reads as empty.
    """
    out = Docstring()
    lines = inspect.cleandoc(text or "").splitlines()
    i = 0
    summary: list[str] = []
    while i < len(lines) and lines[i].strip() and not SECTION.match(lines[i]):
        summary.append(lines[i].strip())
        i += 1
    out.summary = " ".join(summary)
    body: list[str] = []
    while i < len(lines):
        m = SECTION.match(lines[i])
        if not m:
            body.append(lines[i])
            i += 1
            continue
        name, i = m.group(1), i + 1
        block: list[str] = []
        while i < len(lines) and not SECTION.match(lines[i]) and (not lines[i].strip() or lines[i][:1].isspace()):
            block.append(lines[i])
            i += 1
        content = textwrap.dedent("\n".join(block)).strip("\n")
        if name in ("Args", "Arguments"):
            _args(content, out)
        elif name in ("Example", "Examples"):
            out.example = content
        else:
            body += [f"**{name}:**", "", content, ""]
    out.body = "\n".join(body).strip("\n")
    return out


def _args(content: str, out: Docstring) -> None:
    names: list[str] = []
    for line in content.splitlines():
        if not line.strip():
            continue
        if line[:1].isspace():               # a continuation of the entry before
            if not names:
                out.problems.append(f"Args: {line.strip()!r} continues no entry")
                continue
            for n in names:
                out.args[n] = f"{out.args[n]} {line.strip()}".strip()
            continue
        m = ENTRY.match(line)
        if not m:
            out.problems.append(f"Args: {line.strip()!r} is not 'name: description'")
            names = []
            continue
        names = [n.strip().lstrip("*") for n in m.group(1).split(",")]
        for n in names:
            out.args[n] = m.group(2).strip()


def markdown(text: str) -> str:
    """Turns docstring markup into Markdown: reST's double backticks become single ones.

    Args:
        text: a docstring's summary, body or entry.
    """
    return text.replace("``", "`")
