"""A ``Document`` written out: HTML, Markdown, plain text and JSON (``export``), and read back from JSON.

The serializers write the body layer, and the furniture (page headers and footers) only with ``furniture``; other
layers only where ``layers`` names them. JSON is the complete document, every layer (``to_json``; ``from_json``
reads it back).

- **HTML** (``to_html``): an HTML5 document; a title ``h1``, a heading of level n ``h(n+1)`` (at most ``h6``), a
  paragraph ``p``, list items ``li`` in one ``ul``, a note ``aside role="doc-footnote"``, a caption ``p
  class="caption"``, code ``pre``, a page header and footer DPUB-ARIA's ``doc-pageheader`` / ``doc-pagefooter``, a
  formula block its LaTeX between ``\\[`` and ``\\]``, a table ``table_html``, a picture ``figure`` with its image
  and the text read inside it; formatting as ``i``, ``b``, ``u``, ``s``, ``sup``, ``sub`` and ``lang``; line
  breaks ``br``. Writing (``_writing_attributes``): the document's language as ``<html lang>``, its direction as
  ``<html dir="rtl">`` (right to left) or ``<html style="writing-mode: …">`` (vertical); a block's language, where
  it is not the document's, as its element's ``lang``, its direction as ``dir="rtl"``, ``dir="ltr"`` (only in a
  document written right to left) or ``style="writing-mode: …"`` (vertical; ``horizontal-tb`` in a vertical
  document).
- **Markdown** (``to_markdown``, by a policy's ``MarkdownRules``): headings ``#``, list items ``-``, formulas
  ``$$…$$``, tables as the rules say (HTML, or a pipe table unless a cell spans), a picture the rules' placeholder,
  italic ``*``, bold ``**``, strikethrough ``~~``, scripts and underline as HTML with ``html_scripts``, characters
  Markdown would read escaped with ``escape``; ``dividers``: a ``---`` rule between the blocks of one layout region
  and the next. Markdown has no language or direction: they are not written.
- **Text** (``to_text``): each block's text, blocks separated by a blank line; a table one row per line, its cells
  separated by tabs.
"""
from __future__ import annotations

import re

import html as htmllib

from ..data.policy import MarkdownRules
from .model import Block, Document, Span

#: export formats (``export``) -> file extension
EXPORT_FORMATS = {"md": "md", "txt": "txt", "html": "html", "json": "json"}


def load_document(source) -> Document:
    """A ``Document``: as it is, from its dict or JSON, or a transcription's (``build_document``)."""
    from ..data.transcription import Transcription

    if isinstance(source, Document):
        return source
    if isinstance(source, Transcription):
        from .builder import build_document

        return build_document(source)
    if isinstance(source, (str, bytes)):
        return Document.model_validate_json(source)
    return Document.model_validate(source)


def _blocks(doc: Document, furniture: bool, layers) -> list[Block]:
    keep = set(layers) if layers is not None else {"body"}
    if furniture:
        keep.add("furniture")
    return [b for b in doc.blocks if b.layer in keep]


def _segments(text: str, spans: list[Span]) -> list[tuple[str, frozenset, str | None, str | None]]:
    """The text cut at every span boundary: (piece, its formatting, its language, its writing direction)."""
    cuts = sorted({0, len(text), *(max(0, min(len(text), x)) for s in spans for x in (s.start, s.end))})
    out = []
    for a, e in zip(cuts, cuts[1:]):
        fmt, lang, direction = set(), None, None
        for s in spans:
            if s.start <= a and e <= s.end:
                fmt |= {k for k in ("bold", "italic", "underline", "strikethrough") if getattr(s, k)}
                if s.script != "baseline":
                    fmt.add(s.script)
                lang = s.language or lang
                direction = s.direction or direction
                if s.formula:
                    fmt.add("formula")
        out.append((text[a:e], frozenset(fmt), lang, direction))
    return out


# ---------------------------------------------------------------- HTML
_HTML_TAGS = (("bold", "b"), ("italic", "i"), ("underline", "u"), ("strikethrough", "s"), ("super", "sup"),
              ("sub", "sub"))


def _html_inline(b: Block) -> str:
    out = []
    for piece, fmt, lang, direction in _segments(b.text, b.spans):
        s = htmllib.escape(piece, quote=False).replace("\n", "<br>")
        for k, tag in reversed(_HTML_TAGS):
            if k in fmt:
                s = f"<{tag}>{s}</{tag}>"
        bidi = {"horizontal-rl": "rtl", "horizontal-lr": "ltr"}.get(direction or "")
        if lang or bidi:
            attrs = (f' lang="{htmllib.escape(lang)}"' if lang else "") + (f' dir="{bidi}"' if bidi else "")
            s = f"<span{attrs}>{s}</span>"
        out.append(s)
    return "".join(out)


def _cell_pieces(c) -> list[tuple[str, bool]]:
    """A cell's text cut at its formulas: (piece, whether it is a formula)."""
    out, at = [], 0
    for a, e in sorted(c.formulas):
        if a < at or e > len(c.text):
            continue
        if a > at:
            out.append((c.text[at:a], False))
        out.append((c.text[a:e], True))
        at = e
    if at < len(c.text):
        out.append((c.text[at:], False))
    return out


def _cell_dollars(c, escape_dollar: bool) -> str:
    """A cell's text, with ``escape_dollar`` a ``$`` outside its formulas written ``\\$``."""
    if not escape_dollar:
        return c.text
    return "".join(p if f else p.replace("$", "\\$") for p, f in _cell_pieces(c))


def table_html(b: Block, escape_dollar: bool = False, attributes: str = "") -> str:
    """A table block as HTML: rows with their cells' ``rowspan`` and ``colspan``, header cells as ``<th>``, line
    breaks as ``<br>``, text escaped as HTML requires; with ``escape_dollar`` (Markdown's rule, ``MarkdownRules``) a
    ``$`` outside a cell's formulas written ``\\$``; ``attributes`` the ``table`` element's (`` lang="de"``)."""
    esc = lambda c: htmllib.escape(_cell_dollars(c, escape_dollar), quote=False).replace("\n", "<br>")  # noqa: E731
    starts: dict[int, list] = {}
    for c in b.grid.cells:
        starts.setdefault(c.start_row, []).append(c)
    parts = [f"<table{attributes}>"]
    for r in range(b.grid.num_rows):
        parts.append("<tr>")
        for c in sorted(starts.get(r, []), key=lambda x: x.start_col):
            tag = "th" if c.column_header or c.row_header else "td"
            span = (f' rowspan="{c.row_span}"' if c.row_span > 1 else "") + \
                   (f' colspan="{c.col_span}"' if c.col_span > 1 else "")
            parts.append(f"<{tag}{span}>{esc(c)}</{tag}>")
        parts.append("</tr>")
    parts.append("</table>")
    return "".join(parts)


def _writing_attributes(language: str | None, direction: str | None, enclosing_language: str | None = None,
                        enclosing_direction: str | None = None) -> str:
    """An element's ``lang``, ``dir`` and ``style`` (its ``writing-mode``) for ``language`` and ``direction``
    where they differ from what encloses it (the document's): a vertical direction as its writing mode, right to
    left as ``dir="rtl"``, left to right as ``dir="ltr"`` only where it encloses right to left; a horizontal one
    inside a vertical document with ``writing-mode: horizontal-tb``. ``""`` where nothing differs."""
    out = ""
    if language and language != enclosing_language:
        out += f' lang="{htmllib.escape(language)}"'
    if direction and direction != enclosing_direction:
        if direction == "horizontal-rl":
            out += ' dir="rtl"'
        elif direction == "horizontal-lr" and enclosing_direction == "horizontal-rl":
            out += ' dir="ltr"'
        if direction.startswith("vertical"):
            out += f' style="writing-mode: {direction}"'
        elif (enclosing_direction or "").startswith("vertical"):
            out += ' style="writing-mode: horizontal-tb"'
    return out


def _html_block(b: Block, a: str = "") -> str:
    """A block as HTML; ``a``: its outer element's writing attributes (``_writing_attributes``)."""
    inline = _html_inline(b)
    if b.kind == "title":
        return f"<h1{a}>{inline}</h1>"
    if b.kind == "heading":
        n = min((b.level or 1) + 1, 6)
        return f"<h{n}{a}>{inline}</h{n}>"
    if b.kind == "footnote":
        return f'<aside role="doc-footnote"{a}><p>{inline}</p></aside>'
    if b.kind == "page_header":
        return f'<header role="doc-pageheader"{a}><p>{inline}</p></header>'
    if b.kind == "page_footer":
        return f'<footer role="doc-pagefooter"{a}><p>{inline}</p></footer>'
    if b.kind == "code":
        return f"<pre{a}><code>{htmllib.escape(b.text, quote=False)}</code></pre>"
    if b.kind == "formula":
        return f'<div class="formula"{a}>\\[{htmllib.escape(b.text, quote=False)}\\]</div>'
    if b.kind == "table":
        return table_html(b, attributes=a)
    if b.kind == "picture":
        img = f'<img src="{htmllib.escape(b.file)}" alt="">' if b.file else ""
        return f"<figure{a}>{img}{f'<p>{inline}</p>' if b.text else ''}</figure>"
    if b.kind in ("caption", "toc_entry", "reference"):
        return f'<p class="{b.kind.replace("_", "-")}"{a}>{inline}</p>'
    return f"<p{a}>{inline}</p>"


def to_html(source, furniture: bool = False, layers=None) -> str:
    """The document as HTML5 (see the module)."""
    doc = load_document(source)
    out, in_list = [], False
    for b in _blocks(doc, furniture, layers):
        a = _writing_attributes(b.language, b.direction, doc.language, doc.direction)
        if b.kind == "list_item":
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li{a}>{_html_inline(b)}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(_html_block(b, a))
    if in_list:
        out.append("</ul>")
    title = htmllib.escape(doc.name)
    root = _writing_attributes(doc.language, doc.direction)
    return (f'<!DOCTYPE html>\n<html{root}>\n<head>\n<meta charset="utf-8">\n'
            f"<title>{title}</title>\n</head>\n<body>\n" + "\n".join(out) + "\n</body>\n</html>\n")


# ------------------------------------------------------------- Markdown
_INLINE_FORMULA = re.compile(r"(\$[^$\n]+\$)")


def _md_specials(s: str, rules: MarkdownRules, dollar: bool) -> str:
    if rules.escape:
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("_", "\\_")
    return s.replace("$", "\\$") if dollar and rules.escape_dollar else s


def _md_escape(s: str, rules: MarkdownRules) -> str:
    """Markdown's specials escaped in text whose formulas are not known (a table cell's: no formula spans), except
    inside what reads as an inline formula (``$…$``), whose TeX stays as it is."""
    if not rules.escape:
        return s
    return "".join(_md_specials(p, rules, False) if k % 2 == 0 else p
                   for k, p in enumerate(_INLINE_FORMULA.split(s)))


def _md_inline(b: Block, rules: MarkdownRules) -> str:
    out = []
    for piece, fmt, _lang, _direction in _segments(b.text, b.spans):     # a block's formulas are its formula spans
        s = piece if "formula" in fmt else _md_specials(piece, rules, True)
        core = s.strip()
        if not core:
            out.append(s)
            continue
        lead, trail = s[:len(s) - len(s.lstrip())], s[len(s.rstrip()):]
        for k, (a, e) in (("super", ("<sup>", "</sup>")), ("sub", ("<sub>", "</sub>")),
                          ("underline", ("<u>", "</u>"))):
            if k in fmt and rules.html_scripts:
                core = f"{a}{core}{e}"
        if "strikethrough" in fmt:
            core = f"~~{core}~~"
        if "italic" in fmt:
            core = f"*{core}*"
        if "bold" in fmt:
            core = f"**{core}**"
        out.append(lead + core + trail)
    return "".join(out)


def _pipe_table(b: Block, rules: MarkdownRules) -> str:
    rows = [[""] * b.grid.num_cols for _ in range(b.grid.num_rows)]
    for c in b.grid.cells:
        if c.start_row < b.grid.num_rows and c.start_col < b.grid.num_cols:
            text = _cell_dollars(c, rules.escape_dollar)
            rows[c.start_row][c.start_col] = _md_escape(" ".join(text.split()), rules).replace("|", "\\|")
    if not rows:
        return ""
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "|".join("---" for _ in rows[0]) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


#: a row that Markdown would read as a block's start: a heading, quote, list item, ordered item, or a setext
#: heading's underline (or a thematic break)
_MD_ROW_START = re.compile(r"^([#>*+\-])(?=\s|$)")
_MD_ORDERED = re.compile(r"^(\d{1,9})([.)])(?=\s|$)")
_MD_UNDERLINE = re.compile(r"^(=+|-+|\*{3,}|_{3,})\s*$")


def _md_row(row: str) -> str:
    """One row of text escaped where Markdown would read its start as a block's (``# kein Titel``: ``\\# kein
    Titel``; ``1. Mai``: ``1\\. Mai``; a row of ``---`` or ``===``)."""
    lead = row[:len(row) - len(row.lstrip(" "))]
    body = row[len(lead):]
    if _MD_UNDERLINE.match(body) or _MD_ROW_START.match(body):
        return f"{lead}\\{body}"
    m = _MD_ORDERED.match(body)
    return f"{lead}{m.group(1)}\\{body[len(m.group(1)):]}" if m else row


def _md_lines(s: str, rules: MarkdownRules | None = None, b: Block | None = None) -> str:
    """A block's rows in Markdown: a wrap of the layout (``Block.wraps``) as a plain newline (the lines kept in the
    source, a renderer flows them), every other row break (a verse line) as a hard line break (CommonMark's: a
    backslash, or with ``line_break: spaces`` two spaces at the line's end). ``s`` is ``b``'s text as Markdown: its
    newlines are the text's, in order."""
    brk = "  \n" if rules is not None and rules.line_break == "spaces" else "\\\n"
    rows = s.split("\n")
    if rules is None or rules.escape:
        rows = [_md_row(r) for r in rows]
    if b is None or not b.wraps:
        return brk.join(rows)
    wraps = set(b.wraps)
    soft = {k for k, i in enumerate(i for i, c in enumerate(b.text) if c == "\n") if i in wraps}
    return "".join(r + ("" if k == len(rows) - 1 else "\n" if k in soft else brk) for k, r in enumerate(rows))


def _md_block(b: Block, rules: MarkdownRules) -> str:
    if b.kind == "title":
        return "# " + " ".join(_md_inline(b, rules).split("\n"))
    if b.kind == "heading":
        return "#" * min((b.level or 1) + 1, 6) + " " + " ".join(_md_inline(b, rules).split("\n"))
    if b.kind == "list_item":
        return "- " + _md_lines(_md_inline(b, rules), rules, b)
    if b.kind == "code":
        return f"```\n{b.text}\n```"
    if b.kind == "formula":
        return f"${b.text}$" if rules.formula_display == "$" else f"$${b.text}$$"
    if b.kind == "table":
        spans = any(c.row_span > 1 or c.col_span > 1 for c in b.grid.cells)
        return table_html(b, rules.escape_dollar) if rules.tables == "html" or spans else _pipe_table(b, rules)
    if b.kind == "picture":
        parts = [rules.image_placeholder] if rules.image_placeholder else []
        return "\n\n".join(parts + ([_md_lines(_md_inline(b, rules), rules, b)] if b.text else []))
    return _md_lines(_md_inline(b, rules), rules, b)


def to_markdown(source, furniture: bool = False, dividers: bool = False, rules: MarkdownRules | None = None,
                layers=None) -> str:
    """The document as Markdown (see the module); ``dividers``: ``---`` between layout regions."""
    doc = load_document(source)
    rules = rules or MarkdownRules()
    out: list[str] = []
    last, prev_list = None, False
    for b in _blocks(doc, furniture, layers):
        text = _md_block(b, rules)
        if not text.strip():
            continue
        key = (b.origins[0].page, b.origins[0].region) if b.origins else None
        if dividers and out and key != last:
            out.append("---")
        if b.kind == "list_item" and prev_list and out and out[-1] != "---":
            out[-1] += "\n" + text
        else:
            out.append(text)
        last, prev_list = key, b.kind == "list_item"
    return "\n\n".join(out)


# ---------------------------------------------------------------- text
def _text_block(b: Block) -> str:
    if b.kind == "table":
        rows = [[""] * b.grid.num_cols for _ in range(b.grid.num_rows)]
        for c in b.grid.cells:
            if c.start_row < b.grid.num_rows and c.start_col < b.grid.num_cols:
                rows[c.start_row][c.start_col] = " ".join(c.text.split())
        return "\n".join("\t".join(r) for r in rows)
    return b.text


def to_text(source, furniture: bool = False, layers=None) -> str:
    """The document's text: each block's, separated by a blank line."""
    doc = load_document(source)
    return "\n\n".join(x for b in _blocks(doc, furniture, layers) if (x := _text_block(b)).strip())


# ---------------------------------------------------------------- JSON
def to_json(source) -> str:
    """The complete document as JSON (every layer, every origin)."""
    return load_document(source).model_dump_json(by_alias=True, indent=2)


def from_json(text: str | bytes) -> Document:
    return Document.model_validate_json(text)


def export(source, fmt: str, furniture: bool = False, dividers: bool = False, rules: MarkdownRules | None = None) -> str:
    """One export of a document (or of what ``load_document`` makes one of): ``md`` (by the policy's Markdown
    ``rules``; ``dividers`` between layout regions), ``txt``, ``html`` or ``json``. ``furniture`` keeps page headers
    and footers in md, txt and html (json always holds them)."""
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"unknown export format {fmt!r}; choose from {', '.join(EXPORT_FORMATS)}")
    if fmt == "json":
        return to_json(source)
    if fmt == "md":
        return to_markdown(source, furniture, dividers, rules)
    if fmt == "txt":
        return to_text(source, furniture)
    return to_html(source, furniture)


__all__ = ["EXPORT_FORMATS", "export", "from_json", "load_document", "table_html", "to_html", "to_json",
           "to_markdown", "to_text"]
