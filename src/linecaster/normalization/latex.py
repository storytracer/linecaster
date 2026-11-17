"""LaTeX formulas in a text as the characters they print (the ``latex: text`` rule of the normalization
``latex-text``), so that a formula compares equal to the same text typed: ``$\\frac{1}{2}$`` and ``½``, ``$\\alpha$`` and
``α``, ``$x^{2}$`` and ``x²``, ``$Cu_{2}$`` and ``Cu₂`` meet once a lane folds compatibility forms (NFKC: ``½`` is
``1⁄2``, ``²`` and ``₂`` are ``2``). For comparison only: a formula's structure is lost.

What is a formula: ``$$…$$``, ``\\[…\\]``, ``\\(…\\)``, and ``$…$`` whose content is spaced from its dollars (``$ q_1 $``)
or holds LaTeX's ``\\ ^ _ { }`` (``$5 or $10`` is printed text; so is ``$n$``, left for the markup rule, whose letters
are the same). Inside a formula: whitespace is TeX's, not the text's, and goes (explicit spacing ``\\,`` ``\\quad`` ``~``
is a space); ``\\frac{a}{b}`` is ``a⁄b``; ``\\sqrt{x}`` ``√x``; ``\\text{…}``, ``\\mathrm{…}`` and the like their content as
written; an accent (``\\dot{q}``) the letter with its combining mark; ``^`` and ``_`` their argument (``^{\\circ}`` the
degree sign, ``^{\\prime}`` a prime); a symbol macro (``SYMBOLS``) its character; sizing and ``\\left``/``\\right``
nothing; braces go; an unknown macro stays as written. The delimiters go.
"""
from __future__ import annotations

import re

#: macros that print one character
SYMBOLS = {
    **{g: c for g, c in zip(
        "alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi varpi rho "
        "varrho sigma varsigma tau upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi "
        "Psi Omega".split(), "αβγδεεζηθϑικλμνξπϖρϱσςτυφφχψωΓΔΘΛΞΠΣΥΦΨΩ")},
    "times": "×", "cdot": "·", "cdotp": "·", "pm": "±", "mp": "∓", "div": "÷", "ast": "∗", "star": "⋆",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠", "approx": "≈", "sim": "∼", "simeq": "≃",
    "cong": "≅", "equiv": "≡", "propto": "∝", "infty": "∞", "partial": "∂", "nabla": "∇", "sum": "∑", "prod": "∏",
    "int": "∫", "oint": "∮", "circ": "∘", "bullet": "•", "prime": "′", "degree": "°", "ldots": "…", "dots": "…",
    "cdots": "⋯", "vdots": "⋮", "ddots": "⋱", "to": "→", "rightarrow": "→", "leftarrow": "←", "gets": "←",
    "Rightarrow": "⇒", "Leftarrow": "⇐", "leftrightarrow": "↔", "Leftrightarrow": "⇔", "mapsto": "↦",
    "in": "∈", "notin": "∉", "ni": "∋", "subset": "⊂", "supset": "⊃", "subseteq": "⊆", "supseteq": "⊇",
    "cup": "∪", "cap": "∩", "emptyset": "∅", "forall": "∀", "exists": "∃", "neg": "¬", "lnot": "¬", "wedge": "∧",
    "land": "∧", "vee": "∨", "lor": "∨", "angle": "∠", "perp": "⊥", "parallel": "∥", "mid": "∣", "hbar": "ℏ",
    "ell": "ℓ", "aleph": "ℵ", "Re": "ℜ", "Im": "ℑ", "langle": "⟨", "rangle": "⟩", "lfloor": "⌊", "rfloor": "⌋",
    "lceil": "⌈", "rceil": "⌉", "vert": "|", "Vert": "‖", "backslash": "\\", "therefore": "∴", "because": "∵",
    "dagger": "†", "ddagger": "‡", "S": "§", "P": "¶", "pounds": "£", "colon": ":",
    **{f: f for f in "sin cos tan cot sec csc log ln exp lim max min sup inf det arg deg dim gcd sinh cosh tanh".split()},
}
#: macros whose argument is text, written as it is
TEXTUAL = {"text", "textrm", "textit", "textbf", "textsf", "texttt", "textup", "mathrm", "mathit", "mathbf", "mathsf",
           "mathtt", "mathcal", "mathbb", "mathfrak", "mathscr", "boldsymbol", "bm", "operatorname", "mbox", "hbox",
           "emph", "textnormal", "mathnormal"}
FRACTIONS = {"frac", "dfrac", "tfrac", "cfrac"}
#: accents: the combining mark after the letter
ACCENTS = {"dot": "\u0307", "ddot": "\u0308", "bar": "\u0304", "overline": "\u0305", "hat": "\u0302",
           "widehat": "\u0302", "tilde": "\u0303", "widetilde": "\u0303", "vec": "\u20d7", "acute": "\u0301",
           "grave": "\u0300", "breve": "\u0306", "check": "\u030c", "underline": "\u0332"}
SPACES = {"quad", "qquad", "enspace", "thinspace", "medspace", "thickspace", "space"}
#: macros that print nothing (sizing, grouping, style switches)
NOTHING = {"left", "right", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "biggl", "biggr", "middle",
           "displaystyle", "textstyle", "scriptstyle", "limits", "nolimits", "rm", "it", "bf", "cal", "mathop",
           "nonumber", "notag", "label"}
_MACRO = re.compile(r"\\([A-Za-z]+)\*?|\\(.)", re.S)
_MATH = re.compile(r"\$\$(?P<a>.+?)\$\$|\\\[(?P<b>.+?)\\\]|\\\((?P<c>.+?)\\\)"
                   r"|(?<![$\\])\$(?!\$)(?P<d>[^$\n]+?)(?<!\\)\$(?!\$)", re.S)
_LATEXY = re.compile(r"[\\^_{}]")


def _group(s: str, i: int) -> tuple[str, int]:
    """The argument at ``s[i:]``: a braced group's content, a macro, or one character; and where it ends."""
    while i < len(s) and s[i].isspace():
        i += 1
    if i >= len(s):
        return "", i
    if s[i] == "{":
        depth, j = 0, i
        while j < len(s):
            if s[j] == "\\":
                j += 2
                continue
            depth += {"{": 1, "}": -1}.get(s[j], 0)
            if depth == 0:
                return s[i + 1:j], j + 1
            j += 1
        return s[i + 1:], len(s)
    if s[i] == "\\" and (m := _MACRO.match(s, i)):
        return m.group(0), m.end()
    return s[i], i + 1


def math_text(s: str) -> str:
    """The characters a formula's LaTeX ``s`` prints (module docstring)."""
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch.isspace() or ch == "}":
            i += 1
        elif ch == "~":
            out.append(" ")
            i += 1
        elif ch == "{":
            arg, i = _group(s, i)
            out.append(math_text(arg))
        elif ch in "^_":
            arg, i = _group(s, i + 1)
            bare = arg.strip()
            out.append("°" if bare in ("\\circ", "\\degree") and ch == "^" else math_text(arg))
        elif ch == "\\":
            m = _MACRO.match(s, i)
            if m is None:
                out.append(ch)
                i += 1
                continue
            name, single, i = m.group(1), m.group(2), m.end()
            if single is not None:
                out.append({",": " ", ";": " ", ":": " ", " ": " ", "!": "", "\\": " ", "\n": " "}.get(single, single))
            elif name in TEXTUAL:
                arg, i = _group(s, i)
                out.append(" ".join(arg.split()) if name.startswith(("text", "mbox", "hbox", "emph"))
                           else math_text(arg))
            elif name in FRACTIONS:
                a, i = _group(s, i)
                b, i = _group(s, i)
                out.append(f"{math_text(a)}\u2044{math_text(b)}")
            elif name == "sqrt":
                j = i
                while j < len(s) and s[j].isspace():
                    j += 1
                if j < len(s) and s[j] == "[":
                    k = s.find("]", j)
                    i = k + 1 if k > 0 else len(s)
                arg, i = _group(s, i)
                out.append("√" + math_text(arg))
            elif name in ACCENTS:
                arg, i = _group(s, i)
                out.append(math_text(arg) + ACCENTS[name])
            elif name in SYMBOLS:
                out.append(SYMBOLS[name])
            elif name in SPACES:
                out.append(" ")
            elif name not in NOTHING:
                out.append(m.group(0))
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def latex_text(text: str) -> str:
    """``text`` with each formula (module docstring) as the characters it prints, its delimiters gone."""
    def one(m: re.Match) -> str:
        d = m.group("d")
        if d is not None and not (d.strip() and (d[0] == d[-1] == " " or _LATEXY.search(d))):
            return m.group(0)
        return math_text(next(g for g in m.groups() if g is not None))

    return _MATH.sub(one, text)
