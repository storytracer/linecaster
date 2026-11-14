"""HTML -> transcription: ``HtmlImporter`` reads an HTML tree (lxml) into regions, lines, formatting, tables,
formulas and notes, by HTML's own semantics and, where given, a source's conventions (``linecaster.markup``).

**HTML's semantics** (no conventions needed):

- blocks: ``p``, ``div``, ``center``, ``blockquote``, ``section``, ``article``, ``pre``, ``dd``, ``dt``,
  ``figure``; ``h1``-``h6`` are headings of that level; ``li`` a list item; ``hr`` ends a block; ``br`` ends a line;
  whitespace collapses as a browser collapses it;
- formatting: ``i``/``em``/``cite``/``var`` italic, ``b``/``strong`` bold, ``u``/``ins`` underline,
  ``s``/``strike``/``del`` strikethrough, ``sup``/``sub`` script;
- tables (``table``, ``tr``, ``td``/``th`` with ``rowspan``/``colspan``, ``caption``); pictures (``img`` with its
  ``src``, ``figure``, ``figcaption``); formulas (MathML ``math`` with ``alttext``, its LaTeX normalized by
  ``linecaster.text.formulas``);
- DPUB-ARIA roles: ``doc-pageheader`` and ``doc-pagefooter`` are the page's furniture (header, footer),
  ``doc-footnote`` a note, ``doc-noteref`` a note's mark (not text);
- CSS: inline ``display: none`` is removed (``hidden``), ``visibility: hidden`` printed as nothing (a space, a block
  break for a block); ``text-transform`` from the page's ``<style>`` sheets and inline styles, cascaded as a browser
  cascades it, sets the letters' case; ``style``, ``script``, ``head`` and the like are removed (``metadata``).

**Conventions** decide what a source's own markup means (``linecaster.markup.decisions``): a rule's decision on an
element replaces HTML's meaning of it. ``HtmlImporter.DECISIONS`` are the decisions it applies.

Every region and line is read by the people who wrote the source (``people``) unless the rule that made it says
``by: rule`` (then by the importer's annotator). What conventions removed with ``keep_text`` is a region with status
``removed`` and its reason, read but in no text.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ..data.transcription import (
    Annotator, Cell as TableCell, Description, Edit as EditAnnotation, Formatting, Formula, Link, Table, Transcription,
)
from ..markup.apply import Conventions, Coverage
from ..markup.decisions import (
    Block, Break, Caption, Cell, Decision, Describe, Edit, Format, Invisible, Language, Note, Picture, Remove, Unwrap,
)
from ..markup.matchers import TreeMatcher
from ..markup.resolve import ResolvedConventions
from ..text.formulas import clean as clean_formula, layout_brace

BLOCK_TAGS = frozenset({"p", "div", "center", "blockquote", "section", "article", "pre", "dd", "dt", "figure",
                        "dl", "ul", "ol", "address", "main", "nav", "aside", "header", "footer", "body", "html"})
HEADINGS = {f"h{i}": i for i in range(1, 7)}
REMOVED_TAGS = frozenset({"style", "script", "head", "meta", "link", "title", "noscript", "template"})
FORMATS = {"i": "italic", "em": "italic", "cite": "italic", "var": "italic", "b": "bold", "strong": "bold",
           "u": "underline", "ins": "underline", "s": "strikethrough", "strike": "strikethrough",
           "del": "strikethrough", "sup": "super", "sub": "sub"}
HIDDEN = re.compile(r"display\s*:\s*none", re.I)
INVISIBLE = re.compile(r"visibility\s*:\s*hidden", re.I)
#: characters that print nothing (zero-width spaces and joiners, soft hyphens, bidirectional marks)
SILENT = re.compile("[­​-‏⁠-⁤⁦-⁩﻿]")
PARTS = ("header", "body", "footer")


@dataclass
class Run:
    text: str
    fmt: frozenset = frozenset()
    edit: tuple[str, str] | None = None      # (kind, other reading)
    language: str | None = None


@dataclass
class TextBlock:
    """A block being read: its role, runs, and what is attached to it."""

    role: str = "paragraph"
    heading_level: int | None = None
    runs: list[Run] = field(default_factory=list)
    part: str = "body"
    by_rule: bool = False
    rows: list[list[tuple[str, int, int]]] | None = None       # a table: rows of (text, rowspan, colspan)
    file: str | None = None                                    # a picture's file
    status: tuple[str, str] | None = None                      # ("removed", reason) of a removed region kept
    group: int | None = None                                   # cells of one row of cells
    notes: list["TextBlock"] = field(default_factory=list)
    descriptions: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class HtmlReading:
    """What an HTML tree was read into: the transcription, the coverage of the conventions, and whether the page's
    last body block ends there (a ``break`` decision, or not a paragraph) or runs on."""

    transcription: Transcription
    coverage: Coverage
    ends_paragraph: bool


class _CaseCascade:
    """The page's CSS ``text-transform``: its style sheets' rules (outside @-blocks, without pseudo-elements) and
    inline styles, cascaded by importance, specificity and order; inherited."""

    PROPERTY = re.compile(r"text-transform\s*:\s*([a-z-]+)\s*(!\s*important)?", re.I)
    VALUES = frozenset({"uppercase", "lowercase", "capitalize", "none"})

    def __init__(self, root):
        from cssselect import HTMLTranslator, SelectorError, parse

        best: dict = {}
        order = 0
        tr = HTMLTranslator()
        for st in root.iter("style"):
            for selectors, decls in self._rules(st.text or ""):
                m = None
                for m in self.PROPERTY.finditer(decls):
                    pass
                if m is None or m.group(1).lower() not in self.VALUES:
                    continue
                value, important = m.group(1).lower(), bool(m.group(2))
                for sel in selectors.split(","):
                    try:
                        parsed = parse(sel.strip())
                    except SelectorError:
                        continue
                    if len(parsed) != 1 or parsed[0].pseudo_element is not None:
                        continue
                    order += 1
                    key = (important, 0, parsed[0].specificity(), order)
                    for el in root.xpath(tr.selector_to_xpath(parsed[0])):
                        if el not in best or best[el][0] < key:
                            best[el] = (key, value)
        for el in root.iter():
            style = el.get("style") if isinstance(el.tag, str) else None
            if not style or "text-transform" not in style:
                continue
            m = None
            for m in self.PROPERTY.finditer(style):
                pass
            if m is None or m.group(1).lower() not in self.VALUES:
                continue
            order += 1
            key = (bool(m.group(2)), 1, (0, 0, 0), order)
            if el not in best or best[el][0] < key:
                best[el] = (key, m.group(1).lower())
        self.declared = {el: v for el, (_, v) in best.items()}

    @staticmethod
    def _rules(css: str):
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        i, n = 0, len(css)
        while i < n:
            j = css.find("{", i)
            if j < 0:
                return
            head = css[i:j].strip()
            depth, k = 1, j + 1
            while k < n and depth:
                depth += {"{": 1, "}": -1}.get(css[k], 0)
                k += 1
            if not head.startswith("@"):
                yield head, css[j + 1:k - 1]
            i = k

    def value(self, el, inherited: str | None) -> str | None:
        return self.declared.get(el, inherited)

    @staticmethod
    def apply(text: str, value: str | None, prev: str) -> str:
        if not text or value in (None, "none"):
            return text
        if value == "uppercase":
            return text.upper()
        if value == "lowercase":
            return text.lower()
        out = []
        for ch in text:
            out.append(ch.upper() if ch.isalpha() and not (prev.isalnum() or prev in "'’") else ch)
            prev = ch
        return "".join(out)


class HtmlImporter:
    """Reads an HTML tree into a transcription, by HTML's semantics and a source's resolved conventions."""

    DECISIONS = frozenset({"remove", "invisible", "unwrap", "block", "cell", "picture", "caption", "note", "edit",
                           "language", "format", "break", "describe"})

    def __init__(self, conventions: ResolvedConventions | None = None):
        if conventions is not None:
            unknown = sorted({r.decision for r in conventions.rules} - self.DECISIONS)
            if unknown:
                raise ValueError(f"conventions {conventions.ref} use decisions the HTML importer does not apply: "
                                 f"{unknown}")
        self.conventions = Conventions(conventions, TreeMatcher()) if conventions is not None else None

    # ------------------------------------------------------------------------------------------------ reading
    def read(self, root, transcription: Transcription, people: int, rules: int) -> HtmlReading:
        """Reads ``root`` into ``transcription`` (its source and annotators already set): ``people`` and ``rules``
        are the annotators' indices."""
        decided, coverage = self.conventions.decide(root) if self.conventions else ({}, Coverage())
        walk = _Walk(decided, _CaseCascade(root))
        walk.element(root, frozenset(), None, "body")
        walk.flush()
        ends = walk.ends_paragraph()
        _build(transcription, walk.blocks, walk.notes, people, rules)
        return HtmlReading(transcription, coverage, ends)


class _Walk:
    """One walk over the tree: blocks in reading order, notes, and the state of the block being read."""

    def __init__(self, decided: dict, case: _CaseCascade):
        self.decided = decided
        self.case = case
        self.blocks: list[TextBlock] = []
        self.notes: list[TextBlock] = []
        self.cur: TextBlock | None = None
        self.prev = " "                       # the last character read, for capitalize
        self.groups = 0
        self.last_break = False                # a break decision was the last thing in the body
        self.removed: Counter = Counter()

    # -- blocks
    def flush(self):
        if self.cur is not None:
            if "".join(r.text for r in self.cur.runs).strip():
                self.blocks.append(self.cur)
            else:                                        # an empty block: its notes stay, after the blocks
                self.notes += self.cur.notes
        self.cur = None
        self.prev = " "

    def block(self, part: str, **fields) -> TextBlock:
        if self.cur is None:
            self.cur = TextBlock(part=part, **fields)
        return self.cur

    def emit(self, text: str, fmt: frozenset, part: str, case: str | None, **attrs):
        if not text:
            return
        text = self.case.apply(text, case, self.prev)
        self.prev = text[-1]
        self.block(part).runs.append(Run(text, fmt, **attrs))
        if part == "body" and text.strip():
            self.last_break = False

    def ends_paragraph(self) -> bool:
        body = [b for b in self.blocks if b.part == "body" and b.status is None]
        return self.last_break or not body or body[-1].role != "paragraph"

    # -- the walk
    def element(self, el, fmt: frozenset, case: str | None, part: str, attrs: dict | None = None):
        if not isinstance(el.tag, str):                       # comments, processing instructions
            return
        tag = el.tag.lower()
        case = self.case.value(el, case)
        attrs = attrs or {}
        rule = self.decided.get(el)
        if rule is not None:
            if self.decision(el, rule[0], rule[1], fmt, case, part, attrs):
                return
        style = el.get("style") or ""
        role = (el.get("role") or "").lower()
        if tag in REMOVED_TAGS or HIDDEN.search(style):
            self.removed["metadata" if tag in REMOVED_TAGS else "hidden"] += 1
            return
        if INVISIBLE.search(style):
            self.invisible(tag, fmt, part, case)
            return
        if role in ("doc-pageheader", "doc-pagefooter"):
            self.flush()
            self.children(el, fmt, case, "header" if role == "doc-pageheader" else "footer", attrs)
            self.flush()
            return
        if role == "doc-footnote":
            self.note(el, Note(), fmt, case, part)
            return
        if role == "doc-noteref":
            return
        if tag == "br":
            self.emit("\n", fmt, part, None, **attrs)
            self.prev = " "
            return
        if tag == "hr":
            self.flush()
            return
        if tag == "table":
            self.table(el, case, part)
            return
        if tag == "img":
            self.picture(el, Picture(), part)
            return
        if tag == "math":
            self.formula(el, fmt, part, attrs)
            return
        if tag == "figcaption" or tag == "caption":
            self.as_block(el, Block(role="caption"), fmt, case, part, attrs)
            return
        if tag in HEADINGS:
            self.as_block(el, Block(role="heading", heading_level=HEADINGS[tag]), fmt, case, part, attrs)
            return
        if tag == "li":
            self.as_block(el, Block(role="list_item"), fmt, case, part, attrs)
            return
        if tag in BLOCK_TAGS:
            self.flush()
            self.children(el, fmt, case, part, attrs)
            self.flush()
            return
        f = fmt | {FORMATS[tag]} if tag in FORMATS else fmt
        self.children(el, f, case, part, attrs)

    def children(self, el, fmt, case, part, attrs):
        if el.text:
            self.text(el.text, fmt, part, case, attrs)
        for c in el:
            self.element(c, fmt, case, part, attrs)
            if c.tail:
                self.text(c.tail, fmt, part, case, attrs)

    def text(self, value: str, fmt, part, case, attrs):
        self.emit(re.sub(r"\s+", " ", value), fmt, part, case, **attrs)

    def invisible(self, tag: str, fmt, part, case):
        if tag in BLOCK_TAGS or tag in HEADINGS or tag in ("li", "table"):
            self.flush()
        else:
            self.emit(" ", fmt, part, case)

    def as_block(self, el, d: Block, fmt, case, part, attrs, by_rule: bool = False):
        self.flush()
        self.block(part, role=d.role, heading_level=d.heading_level, by_rule=by_rule)
        self.children(el, fmt, case, part, attrs)
        self.flush()

    # -- decisions
    def decision(self, el, rule_id: str, d: Decision, fmt, case, part, attrs) -> bool:
        """Applies ``d`` to ``el``; ``False``: read the element as HTML after all (a decision that only adds)."""
        tag = el.tag.lower()
        match d:
            case Remove(reason=reason, keep_text=keep):
                self.removed[reason] += 1
                text = " ".join("".join(el.itertext()).split()) if keep else ""
                if text:
                    self.blocks.append(TextBlock(role="other", runs=[Run(text)], part=part,
                                                 status=("removed", reason)))
            case Invisible():
                self.invisible(tag, fmt, part, case)
            case Unwrap():
                self.children(el, fmt, case, part, attrs)
            case Block():
                self.as_block(el, d, fmt, case, part, attrs, by_rule=False)
            case Cell(role=role):                     # the cells under one parent: one row of cells
                self.flush()
                cell = self.block(part, role=role, group=id(el.getparent()))
                self.children(el, fmt, case, part, attrs)
                self.cur = None
                self.blocks.append(cell)
                self.notes += cell.notes
                cell.notes = []
            case Picture():
                self.picture(el, d, part)
            case Caption():
                self.as_block(el, Block(role="caption"), fmt, case, part, attrs)
            case Note():
                self.note(el, d, fmt, case, part)
            case Edit(kind=kind, attr=attr):
                other = el.get(attr)
                self.children(el, fmt, case, part, {**attrs, "edit": (kind, other)} if other else attrs)
            case Language(attr=attr):
                lang = el.get(attr)
                self.children(el, fmt, case, part, {**attrs, "language": lang} if lang else attrs)
            case Format():
                f = {k for k in ("bold", "italic", "underline", "strikethrough") if getattr(d, k)}
                if d.script != "baseline":
                    f.add(d.script)
                self.children(el, fmt | f, case, part, attrs)
            case Break(run_on=run_on):
                self.flush()
                if part == "body":
                    self.last_break = not run_on
            case Describe(kind=kind, attr=attr):
                text = el.get(attr) if attr else " ".join("".join(el.itertext()).split())
                if text:
                    self.block(part).descriptions.append((kind, text))
            case _:
                return False
        return True

    def note(self, el, d: Note, fmt, case, part):
        host = self.block(part)
        saved, self.cur = self.cur, None
        sub = _Walk(self.decided, self.case)
        sub.block(part, role="footnote_continued" if d.continued else "footnote")
        sub.children(el, fmt, case, part, {})
        sub.flush()
        runs: list[Run] = []
        for b in sub.blocks:
            if runs and b.runs:
                runs.append(Run("\n"))
            runs += b.runs
        if "".join(r.text for r in runs).strip():
            host.notes.append(TextBlock(role="footnote_continued" if d.continued else "footnote", runs=runs,
                                        part=part))
        self.notes += sub.notes
        self.cur = saved

    def picture(self, el, d: Picture, part):
        src = el.get(d.attr) or next((e.get(d.attr) for e in el.iterdescendants() if isinstance(e.tag, str)
                                      and e.get(d.attr)), None)
        self.flush()
        self.blocks.append(TextBlock(role="picture", part=part, file=src))

    def formula(self, el, fmt, part, attrs):
        tex = clean_formula(el.get("alttext") or "")
        if not tex:
            return
        brace = layout_brace(tex)
        if brace:
            self.emit(brace, fmt, part, None, **attrs)
            return
        block = (el.get("display") or "").lower() == "block"
        if block:
            self.flush()
        self.emit(f"${tex}$", fmt | {"formula"}, part, None, **attrs)
        if block:
            self.flush()

    def table(self, el, case, part):
        self.flush()
        rows: list[list[tuple[str, int, int]]] = []
        caption = None
        for x in el.iter():
            if not isinstance(x.tag, str):
                continue
            t = x.tag.lower()
            if t == "caption" and x.getparent() is el:
                caption = x
            if t == "tr" and _owner(x) is el:
                cells = []
                for c in x:
                    if isinstance(c.tag, str) and c.tag.lower() in ("td", "th"):
                        sub = _Walk(self.decided, self.case)
                        sub.children(c, frozenset(), self.case.value(c, case), part, {})
                        sub.flush()
                        self.notes += sub.notes + [n for b in sub.blocks for n in b.notes]
                        text = "\n".join(_block_text(b) for b in sub.blocks if b.file is None)
                        cells.append((text, _span(c.get("rowspan")), _span(c.get("colspan"))))
                        for b in sub.blocks:
                            if b.file is not None:
                                self.blocks.append(b)
                rows.append(cells)
        if caption is not None:
            self.as_block(caption, Block(role="caption"), frozenset(), case, part, {})
        if any(rows):
            self.blocks.append(TextBlock(role="table", part=part, rows=[r for r in rows if r]))


def _owner(tr):
    """The table a row belongs to (its nearest table ancestor)."""
    for a in tr.iterancestors():
        if isinstance(a.tag, str) and a.tag.lower() == "table":
            return a
    return None


def _span(v: str | None) -> int:
    try:
        return max(1, int(v)) if v else 1
    except ValueError:
        return 1


def _block_text(b: TextBlock) -> str:
    """A block's text; a table's: its cells' texts in order."""
    if b.rows is not None:
        return " ".join(text for row in b.rows for text, _, _ in row if text)
    return "\n".join(t for t, _ in _lines(b.runs))


def _lines(runs: list[Run]) -> list[tuple[str, list[tuple[int, int, Run]]]]:
    """A block's runs as lines: (text, whitespace collapsed as rendered, [(start, end, run)] per run in it)."""
    lines, cur = [], []
    for r in runs:
        for k, part in enumerate(r.text.split("\n")):
            if k:
                lines.append(cur)
                cur = []
            if part:
                cur.append(Run(part, r.fmt, r.edit, r.language))
    lines.append(cur)
    out = []
    for runs_ in lines:
        text, spans = "", []
        for r in runs_:
            t = re.sub(r"\s+", " ", SILENT.sub("", r.text))
            if (not text or text.endswith(" ")) and t.startswith(" "):
                t = t[1:]
            spans.append((len(text), len(text) + len(t), r))
            text += t
        if text.endswith(" "):
            text = text[:-1]
            spans = [(a, min(b, len(text)), r) for a, b, r in spans]
        if text:
            out.append((text, spans))
    return out


def _build(t: Transcription, blocks: list[TextBlock], notes: list[TextBlock], people: int, rules: int) -> None:
    """The blocks as regions and lines of ``t``: header first, then the body's blocks with their notes after them,
    then the footer; reading order by part."""
    order: list[str] = []
    line_order: list[str] = []
    counter: Counter = Counter()

    def new_id(role: str) -> str:
        counter[role] += 1
        return f"{role}_{counter[role] - 1}"

    def lines(rid: str, b: TextBlock, who: int):
        for j, (text, spans) in enumerate(_lines(b.runs)):
            lid = f"{rid}_l{j}"
            ln = t.add_line(who, lid, region=rid, text=text)
            fmts = []
            for a, e, r in spans:
                if e <= a:
                    continue
                if "formula" in r.fmt:
                    t.formulas.append(Formula(annotator=who, target=f"{lid}[{a}:{e}]", latex=text[a + 1:e - 1]))
                    continue
                f = {k: True for k in ("italic", "bold", "underline", "strikethrough") if k in r.fmt}
                f.update({"script": s} for s in ("super", "sub") if s in r.fmt)
                if f:
                    fmts.append(Formatting(charspan=[a, e], **f))
                if r.edit is not None:
                    t.edits.append(EditAnnotation(annotator=who, target=f"{lid}[{a}:{e}]", kind=r.edit[0],
                                                  text=r.edit[1]))
                if r.language:
                    t.classify(who, f"{lid}[{a}:{e}]", "language", r.language)
            if fmts:
                ln.reading.formatting = fmts
            if b.status is None:
                line_order.append(lid)

    def region(b: TextBlock, parent: str | None = None) -> str:
        who = rules if b.by_rule else people
        role = b.role if b.part == "body" or b.role != "paragraph" else b.part     # furniture's text: header, footer
        rid = new_id(role if b.status is None else "removed")
        t.add_region(who, rid, label=role, role=role if b.status is None else "other",
                     heading_level=b.heading_level, parent=parent)
        if b.status is not None:
            t.classify(rules, rid, "status", b.status[0], reason=b.status[1])
        if b.file is not None:
            setattr(t.region(rid), "html__src", b.file)
        for kind, text in b.descriptions:
            t.descriptions.append(Description(annotator=who, target=rid, kind=kind, text=text))
        if b.rows is not None:
            cells, grid = [], {}
            for i, row in enumerate(b.rows):
                j = 0
                for text, rs, cs in row:
                    while (i, j) in grid:
                        j += 1
                    for di in range(rs):
                        for dj in range(cs):
                            grid[(i + di, j + dj)] = True
                    cells.append(TableCell(start_row=i, end_row=i + rs, start_col=j, end_col=j + cs, text=text))
                    j += cs
            t.tables.append(Table(annotator=who, target=rid, num_rows=max((c.end_row for c in cells), default=0),
                                  num_cols=max((c.end_col for c in cells), default=0), cells=cells))
            b = TextBlock(role=b.role, runs=[Run(" ".join(c.text.replace("\n", " ") for c in cells if c.text))],
                          part=b.part)
        if b.status is None:
            order.append(rid)
        lines(rid, b, who)
        return rid

    def part(name: str):
        bs = [b for b in blocks if b.part == name]
        k = 0
        while k < len(bs):
            b = bs[k]
            if b.group is not None:                     # a row of cells: one region, a region per cell
                group = [x for x in bs[k:] if x.group == b.group]
                k += len(group)
                rid = new_id(b.role)
                t.add_region(people, rid, label=b.role, role=b.role)
                order.append(rid)
                for c in group:
                    if c.runs:
                        region(c, parent=rid)
                continue
            rid = region(b)
            for n in b.notes:
                nid = region(n)
                t.links.append(Link(annotator=people, kind="note_of", source=nid, target=rid))
            k += 1

    part("header")
    part("body")
    for n in notes:
        region(n)
    part("footer")
    t.add_order(people, order, line_order)
