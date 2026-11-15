"""A ``Document`` written out: HTML, Markdown, plain text and JSON (``export``), and read back from JSON.

The serializers write the body layer, and the furniture (page headers and footers) only with ``furniture``; other
layers only where ``layers`` names them. JSON is the complete document, every layer (``to_json``; ``from_json``
reads it back).

- **HTML** (``to_html``): an HTML5 document; a title ``h1``, a heading of level n ``h(n+1)`` (at most ``h6``), a
  paragraph ``p``, list items ``li`` in one ``ul``, a note ``aside role="doc-footnote"``, a caption ``p
  class="caption"``, code ``pre``, a page header and footer DPUB-ARIA's ``doc-pageheader`` / ``doc-pagefooter``, a
  formula block its LaTeX between ``\\[`` and ``\\]``, a table ``table_html``, a picture ``figure`` with its image
  and the text read inside it; formatting as ``i``, ``b``, ``u``, ``s``, ``sup``, ``sub`` and ``lang``; line
  breaks ``br``.
- **Markdown** (``to_markdown``, by a policy's ``MarkdownRules``): headings ``#``, list items ``-``, formulas
  ``$$…$$``, tables as the rules say (HTML, or a pipe table unless a cell spans; as HTML each cell's text is Markdown
  between blank lines, which a viewer renders), rows as hard line breaks, a picture the rules' placeholder,
  italic ``*``, bold ``**``, strikethrough ``~~``, scripts and underline as HTML with ``html_scripts``, characters
  Markdown would read escaped with ``escape``; ``dividers``: a ``---`` rule between the blocks of one layout region
  and the next.
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


def _segments(text: str, spans: list[Span]) -> list[tuple[str, frozenset, str | None]]:
    """The text cut at every span boundary: (piece, its formatting, its language)."""
    cuts = sorted({0, len(text), *(max(0, min(len(text), x)) for s in spans for x in (s.start, s.end))})
    out = []
    for a, e in zip(cuts, cuts[1:]):
        fmt, lang = set(), None
        for s in spans:
            if s.start <= a and e <= s.end:
                fmt |= {k for k in ("bold", "italic", "underline", "strikethrough") if getattr(s, k)}
                if s.script != "baseline":
                    fmt.add(s.script)
                lang = s.language or lang
        out.append((text[a:e], frozenset(fmt), lang))
    return out


# ---------------------------------------------------------------- HTML
_HTML_TAGS = (("bold", "b"), ("italic", "i"), ("underline", "u"), ("strikethrough", "s"), ("super", "sup"),
              ("sub", "sub"))


def _html_inline(b: Block) -> str:
    out = []
    for piece, fmt, lang in _segments(b.text, b.spans):
        s = htmllib.escape(piece, quote=False).replace("\n", "<br>")
        for k, tag in reversed(_HTML_TAGS):
            if k in fmt:
                s = f"<{tag}>{s}</{tag}>"
        if lang:
            s = f'<span lang="{htmllib.escape(lang)}">{s}</span>'
        out.append(s)
    return "".join(out)


def table_html(b: Block) -> str:
    """A table block as HTML: rows with their cells' ``rowspan`` and ``colspan``, header cells as ``<th>``, line
    breaks as ``<br>``, text escaped as HTML requires."""
    esc = lambda s: htmllib.escape(s, quote=False).replace("\n", "<br>")   # noqa: E731
    starts: dict[int, list] = {}
    for c in b.grid.cells:
        starts.setdefault(c.start_row, []).append(c)
    parts = ["<table>"]
    for r in range(b.grid.num_rows):
        parts.append("<tr>")
        for c in sorted(starts.get(r, []), key=lambda x: x.start_col):
            tag = "th" if c.column_header or c.row_header else "td"
            span = (f' rowspan="{c.row_span}"' if c.row_span > 1 else "") + \
                   (f' colspan="{c.col_span}"' if c.col_span > 1 else "")
            parts.append(f"<{tag}{span}>{esc(c.text)}</{tag}>")
        parts.append("</tr>")
    parts.append("</table>")
    return "".join(parts)


def _html_block(b: Block) -> str:
    inline = _html_inline(b)
    if b.kind == "title":
        return f"<h1>{inline}</h1>"
    if b.kind == "heading":
        n = min((b.level or 1) + 1, 6)
        return f"<h{n}>{inline}</h{n}>"
    if b.kind == "footnote":
        return f'<aside role="doc-footnote"><p>{inline}</p></aside>'
    if b.kind == "page_header":
        return f'<header role="doc-pageheader"><p>{inline}</p></header>'
    if b.kind == "page_footer":
        return f'<footer role="doc-pagefooter"><p>{inline}</p></footer>'
    if b.kind == "code":
        return f"<pre><code>{htmllib.escape(b.text, quote=False)}</code></pre>"
    if b.kind == "formula":
        return f'<div class="formula">\\[{htmllib.escape(b.text, quote=False)}\\]</div>'
    if b.kind == "table":
        return table_html(b)
    if b.kind == "picture":
        img = f'<img src="{htmllib.escape(b.file)}" alt="">' if b.file else ""
        return f"<figure>{img}{f'<p>{inline}</p>' if b.text else ''}</figure>"
    if b.kind in ("caption", "toc_entry", "reference"):
        return f'<p class="{b.kind.replace("_", "-")}">{inline}</p>'
    return f"<p>{inline}</p>"


def to_html(source, furniture: bool = False, layers=None) -> str:
    """The document as HTML5 (see the module)."""
    doc = load_document(source)
    out, in_list = [], False
    for b in _blocks(doc, furniture, layers):
        if b.kind == "list_item":
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_html_inline(b)}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(_html_block(b))
    if in_list:
        out.append("</ul>")
    title = htmllib.escape(doc.name)
    return ('<!DOCTYPE html>\n<html>\n<head>\n<meta charset="utf-8">\n'
            f"<title>{title}</title>\n</head>\n<body>\n" + "\n".join(out) + "\n</body>\n</html>\n")


# ------------------------------------------------------------- Markdown
_INLINE_FORMULA = re.compile(r"(\$[^$\n]+\$)")


def _md_escape(s: str, rules: MarkdownRules) -> str:
    """Markdown's specials escaped, except inside an inline formula (``$…$``), whose TeX stays as it is."""
    if not rules.escape:
        return s
    out = []
    for k, piece in enumerate(_INLINE_FORMULA.split(s)):
        if k % 2 == 0:
            piece = piece.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("_", "\\_")
        out.append(piece)
    return "".join(out)


def _md_inline(b: Block, rules: MarkdownRules) -> str:
    out = []
    for piece, fmt, _lang in _segments(b.text, b.spans):
        s = _md_escape(piece, rules)
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
            rows[c.start_row][c.start_col] = _md_escape(" ".join(c.text.split()), rules).replace("|", "\\|")
    if not rows:
        return ""
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "|".join("---" for _ in rows[0]) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _md_lines(s: str) -> str:
    """A block's rows as Markdown's hard line breaks (a backslash at the line's end, CommonMark's), which a plain
    newline inside a paragraph is not."""
    return "\\\n".join(s.split("\n"))


def _md_table_html(b: Block, rules: MarkdownRules) -> str:
    """A table as HTML inside Markdown, each cell's text as Markdown between blank lines: CommonMark ends an HTML
    block at a blank line and reads what follows as Markdown, so a cell's formulas, escapes and line breaks render
    in a viewer as they do outside the table."""
    starts: dict[int, list] = {}
    for c in b.grid.cells:
        starts.setdefault(c.start_row, []).append(c)
    out = ["<table>"]
    for r in range(b.grid.num_rows):
        out.append("<tr>")
        for c in sorted(starts.get(r, []), key=lambda x: x.start_col):
            tag = "th" if c.column_header or c.row_header else "td"
            span = (f' rowspan="{c.row_span}"' if c.row_span > 1 else "") + \
                   (f' colspan="{c.col_span}"' if c.col_span > 1 else "")
            text = "\n".join(ln.strip() for ln in c.text.strip().split("\n"))
            if text:
                out.append(f"<{tag}{span}>\n\n{_md_lines(_md_escape(text, rules))}\n\n</{tag}>")
            else:
                out.append(f"<{tag}{span}></{tag}>")
        out.append("</tr>")
    out.append("</table>")
    return "\n".join(out)


def _md_block(b: Block, rules: MarkdownRules) -> str:
    if b.kind == "title":
        return "# " + " ".join(_md_inline(b, rules).split("\n"))
    if b.kind == "heading":
        return "#" * min((b.level or 1) + 1, 6) + " " + " ".join(_md_inline(b, rules).split("\n"))
    if b.kind == "list_item":
        return "- " + _md_lines(_md_inline(b, rules))
    if b.kind == "code":
        return f"```\n{b.text}\n```"
    if b.kind == "formula":
        return f"$${b.text}$$"
    if b.kind == "table":
        spans = any(c.row_span > 1 or c.col_span > 1 for c in b.grid.cells)
        return _md_table_html(b, rules) if rules.tables == "html" or spans else _pipe_table(b, rules)
    if b.kind == "picture":
        parts = [rules.image_placeholder] if rules.image_placeholder else []
        return "\n\n".join(parts + ([_md_lines(_md_inline(b, rules))] if b.text else []))
    return _md_lines(_md_inline(b, rules))


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
