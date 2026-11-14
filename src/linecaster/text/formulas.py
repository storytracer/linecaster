"""Formulas as their content: LaTeX with every command that only sets the formula's presentation removed, so a
reference holds what the formula says, as OmniDocBench's and olmOCR-Bench's references do. Importers normalize the
LaTeX a source gives (MathML's ``alttext``, a wiki's ``<math>``) with ``clean``; the source's own LaTeX stays with
the source.

Removed (presentation only):
- a wrapper ``{\\displaystyle …}`` and any brace pair left around the whole formula;
- size: ``\\displaystyle``, ``\\textstyle``, ``\\scriptstyle``, ``\\scriptscriptstyle``;
- spacing: ``\\,`` ``\\;`` ``\\:`` ``\\!``, ``\\quad``, ``\\qquad``, ``\\enspace``, ``\\thinspace``, ``\\medspace``,
  ``\\thickspace`` and their negative forms, ``\\hspace{…}``, ``\\vspace{…}``, ``\\kern``/``\\mkern``/``\\hskip``/
  ``\\mskip`` with their dimension;
- delimiter sizing: ``\\left``, ``\\right``, ``\\middle``, ``\\big``… ``\\Bigg`` (with l/r/m): the command goes, the
  delimiter stays (``\\left(`` -> ``(``), except the empty delimiter ``.``, which goes too;
- colour and invisible boxes: ``\\color{…}``, ``\\textcolor{…}`` (its text stays), ``\\phantom``, ``\\hphantom``,
  ``\\vphantom`` with their argument; ``\\color{white}`` hides the rest of its group, ``\\textcolor{white}{x}``
  hides x.

Kept: everything else, including font commands (``\\mathrm``, ``\\mathbf``, …), ``\\text{…}``, environments and
their line breaks, and the explicit space ``\\ ``. Runs of whitespace become one space; a space is kept wherever
removing a command would join a command name to the letter after it. ``layout_brace``: a formula that is only a
tall curly brace (an empty matrix beside a brace, which some sources use to draw one) is the brace character.
"""
from __future__ import annotations

import re

STYLE = {"displaystyle", "textstyle", "scriptstyle", "scriptscriptstyle"}
SPACE_WORDS = {"quad", "qquad", "enspace", "thinspace", "medspace", "thickspace", "negthinspace", "negmedspace",
               "negthickspace"}
SPACE_SYMBOLS = {",", ";", ":", "!"}
DIMENSION_CMDS = {"kern", "mkern", "hskip", "mskip"}
WITH_ARG = {"hspace", "vspace", "phantom", "hphantom", "vphantom", "color"}
SIZERS = {"left", "right", "middle"} | {b + s for b in ("big", "Big", "bigg", "Bigg") for s in ("", "l", "r", "m")}

_TOKEN = re.compile(r"\\[A-Za-z]+\*?|\\.|\s+|.", re.S)
_DIMENSION = re.compile(r"\s*[-+]?(\d+\.?\d*|\.\d+)\s*(pt|mu|em|ex|mm|cm|in|bp|pc|dd|cc|sp)")


def _group_end(tokens: list[str], i: int) -> int:
    """Index after the brace group starting at tokens[i] (or after the single token at i)."""
    while i < len(tokens) and tokens[i].isspace():
        i += 1
    if i >= len(tokens) or tokens[i] != "{":
        return i + 1
    depth = 0
    for j in range(i, len(tokens)):
        depth += (tokens[j] == "{") - (tokens[j] == "}")
        if depth == 0:
            return j + 1
    return len(tokens)


def _arg(tokens: list[str], i: int) -> str:
    """The text of the brace group (or single token) starting at tokens[i], without its braces."""
    while i < len(tokens) and tokens[i].isspace():
        i += 1
    end = _group_end(tokens, i)
    inner = tokens[i + 1:end - 1] if i < len(tokens) and tokens[i] == "{" else tokens[i:end]
    return "".join(inner).strip()


def _rest_of_group(tokens: list[str], i: int) -> int:
    """Index of the brace that closes the group tokens[i] is in (len(tokens) at the top level)."""
    depth = 0
    for j in range(i, len(tokens)):
        depth += (tokens[j] == "{") - (tokens[j] == "}")
        if depth < 0:
            return j
    return len(tokens)


def _strip(tokens: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        name = t[1:].rstrip("*") if t.startswith("\\") and len(t) > 1 and t[1].isalpha() else None
        if name in STYLE or name in SPACE_WORDS or (t.startswith("\\") and t[1:] in SPACE_SYMBOLS):
            i += 1
        elif name in DIMENSION_CMDS:
            m = _DIMENSION.match("".join(tokens[i + 1:i + 12]))
            i += 1
            if m:                                          # skip the tokens that make up the dimension
                taken = 0
                while i < len(tokens) and taken < m.end():
                    taken += len(tokens[i])
                    i += 1
        elif name in ("color", "textcolor") and _arg(tokens, i + 1) == "white":
            # white is invisible on the page: \color{white} hides the rest of its group, \textcolor{white}{x} hides x
            j = _group_end(tokens, i + 1)
            i = _group_end(tokens, j) if name == "textcolor" else _rest_of_group(tokens, j)
        elif name in WITH_ARG:
            i = _group_end(tokens, i + 1)
        elif name == "textcolor":                          # \textcolor{colour}{text}: keep the text
            i = _group_end(tokens, i + 1)
        elif name in SIZERS:
            i += 1
            while i < len(tokens) and tokens[i].isspace():
                i += 1
            if i < len(tokens) and tokens[i] == ".":       # the empty delimiter of \left. / \right.
                i += 1
        else:
            out.append(t)
            i += 1
            continue
        while i < len(tokens) and tokens[i].isspace():    # the space after a removed command ends its name only
            i += 1
    return out


def _join(tokens: list[str]) -> str:
    s = ""
    for t in tokens:
        if t.isspace():
            t = " "
            if s.endswith(" ") or not s:
                continue
        elif re.search(r"\\[A-Za-z]+$", s) and t[0].isalpha():
            s += " "                                       # \cdot\,x -> "\cdot x", not "\cdotx"
        s += t
    return s.strip()


def _unwrap(tokens: list[str]) -> list[str]:
    """Remove brace pairs that enclose the whole formula (on tokens, so `\\{` and `\\\\` are never braces)."""
    while True:
        while tokens and tokens[0].isspace():
            tokens = tokens[1:]
        while tokens and tokens[-1].isspace():
            tokens = tokens[:-1]
        if tokens and tokens[0] == "{" and _group_end(tokens, 0) == len(tokens):
            tokens = tokens[1:-1]
        else:
            return tokens


def clean(alttext: str) -> str:
    """The formula's content: `alttext` without presentation commands (see the module docstring)."""
    return _join(_unwrap(_strip(_TOKEN.findall(alttext or ""))))


_EMPTY_MATRIX = re.compile(r"\\begin\{matrix\}(?:\s|\\ |\\\\|&)*\\end\{matrix\}")
_BRACE_IN_MATRIX = re.compile(r"^\\begin\{matrix\}\s*\{?\s*\\([{}])\s*\}?\s*\\end\{matrix\}$")


def layout_brace(tex: str) -> str | None:
    """The brace character if a cleaned formula is only a tall curly brace (sources that draw a brace render
    an empty matrix, whose rows give the height, beside \\{ or \\}; or a lone brace inside a matrix), else None.
    Such a formula is layout: the page prints a brace, so the text gets the plain character."""
    t = _unwrap_text(tex)
    m = _BRACE_IN_MATRIX.match(t)
    if m:
        return m.group(1)
    if not _EMPTY_MATRIX.search(t):
        return None
    shape = re.sub(r"[{}\s]", "", _EMPTY_MATRIX.sub("M", t).replace("\\{", "L").replace("\\}", "R"))
    return {"LM": "{", "MR": "}"}.get(shape)


def _unwrap_text(tex: str) -> str:
    return _join(_unwrap(_TOKEN.findall(tex or "")))
