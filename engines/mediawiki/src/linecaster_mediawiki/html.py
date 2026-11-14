"""wikitextprocessor's parse of expanded wikitext -> an HTML document (lxml), as MediaWiki renders wikitext, for
linecaster's HTML importer.

MediaWiki's rules this follows: a blank line ends a paragraph (inline elements open across it are closed and opened
again, as browsers repair MediaWiki's output); block elements (``div``, ``table``, ``center``, ``blockquote``, lists,
headings, ``hr``) end the paragraph around them; a line that starts with a space is preformatted; ``''``/``'''`` are
italic and bold; ``[[link|label]]`` prints its label, a category link nothing, a file link a picture (with its
caption where it is framed: ``thumb``, ``frame``); ``[url label]`` its label. Entities are decoded.

MediaWiki's extensions, written as standard HTML the importer knows: Cite's ``<ref>`` is a DPUB-ARIA
``doc-footnote`` where its mark stands (a ``follow=`` note has the class ``mw-ref-follow``, a reuse of a named note
is nothing); ``<references>`` prints nothing (the notes are where their marks are); Math's ``<math>`` and Chem's
``<chem>``/``<ce>`` are MathML ``math`` elements with the TeX in ``alttext``; Poem's ``<poem>`` a ``div`` with a line
break per line and a paragraph per stanza; Gallery's files pictures with their captions; TemplateStyles' style
sheets ``<style>`` elements (from the wiki's pages, their ``.mw-parser-output`` scope removed); ProofreadPage's header
and footer ``doc-pageheader`` and ``doc-pagefooter``.

Blocks are given to the part of the page their source lies in (the parsed text's markers): a block wholly in the
header is the header's, wholly in the footer the footer's, any other the body's; a paragraph that runs on from the
body into the footer is split there.
"""
from __future__ import annotations

import html as htmllib
import re
from dataclasses import dataclass, field

from lxml import etree

from .proofread import FOOT_START, HEAD_END

BLOCK_TAGS = frozenset({"div", "p", "center", "blockquote", "table", "ul", "ol", "dl", "li", "dd", "dt", "h1", "h2",
                        "h3", "h4", "h5", "h6", "pre", "hr", "section", "figure", "caption", "tr", "td", "th",
                        "tbody", "thead", "tfoot"})
#: extension tags whose content prints nothing where they stand
SILENT = frozenset({"references", "pagequality", "section", "templatedata", "indicator", "pagelist", "noinclude",
                    "includeonly", "onlyinclude", "nowiki-stub", "charinsert", "imagemap", "timeline", "score",
                    "syntaxhighlight-stub"})
FRAMED = frozenset({"thumb", "thumbnail", "frame", "framed"})
PARAGRAPH = re.compile(r"\n[ \t]*\n\s*")
PARTS = ("header", "body", "footer")
EMPTY_NOWIKI = re.compile(r"<nowiki\s*/>|<nowiki\s*>\s*</nowiki\s*>", re.I)
TEMPLATESTYLES = re.compile(r"<templatestyles\s+src\s*=\s*[\"']?([^\"'/>]+(?:/[^\"'/>]+)*)[\"']?\s*/?>", re.I)


@dataclass
class Built:
    """The HTML document and what the build met that it could not read (template calls left unexpanded)."""

    root: etree._Element
    unexpanded: list[str] = field(default_factory=list)


class HtmlBuilder:
    """Builds the HTML of one parsed page. ``site`` tells file and category links apart; ``styles(title)`` gives a
    TemplateStyles style sheet's text."""

    def __init__(self, site, styles=None):
        self.site = site
        self.styles = styles or (lambda title: None)

    def build(self, root) -> Built:
        w = _Writer(self)
        w.nodes(root.children)
        return Built(w.finish(), w.unexpanded)


class _Writer:
    def __init__(self, builder: HtmlBuilder):
        self.b = builder
        self.doc = etree.Element("html")
        self.body = etree.SubElement(self.doc, "body")
        self.top: list[tuple[etree._Element, set[str]]] = []      # top-level blocks and the parts they lie in
        self.container = self.body
        self.p: etree._Element | None = None
        self.inline: list[etree._Element] = []                    # open inline elements of the paragraph
        self.cursor: etree._Element | None = None
        self.part = "header"
        self.unexpanded: list[str] = []
        self.pre = 0
        self.styles_seen: set[str] = set()

    # ------------------------------------------------------------------------------------------------ output
    def _top_block(self, el) -> None:
        if self.container is self.body:
            self.top.append((el, {self.part}))
        else:
            self.top[-1][1].add(self.part) if self.top else None

    def ensure_p(self) -> etree._Element:
        if self.p is None:
            self.p = etree.SubElement(self.container, "p")
            self._top_block(self.p)
            cur = self.p
            reopened = []
            for el in self.inline:
                c = etree.SubElement(cur, el.tag, dict(el.attrib))
                reopened.append(c)
                cur = c
            self.inline = reopened
            self.cursor = cur
        return self.cursor

    def append_text(self, text: str) -> None:
        if not text:
            return
        cur = self.ensure_p()
        if len(cur):
            last = cur[-1]
            last.tail = (last.tail or "") + text
        else:
            cur.text = (cur.text or "") + text

    def paragraph_break(self) -> None:
        self.p = None
        self.cursor = None

    def mark(self, part: str) -> None:
        """A part's boundary: the paragraph ends there, and what follows lies in ``part``."""
        self.paragraph_break()
        self.part = part
        if self.container is not self.body and self.top:
            self.top[-1][1].add(part)

    def text(self, s: str) -> None:
        if "templatestyles" in s.lower():               # left as text where wikitextprocessor does not take the tag
            s = TEMPLATESTYLES.sub(lambda m: self.style(m.group(1)) or "", s)
        if "nowiki" in s.lower():                       # an empty <nowiki/> separates wikitext and prints nothing
            s = EMPTY_NOWIKI.sub("", s)
        s = htmllib.unescape(s)
        if self.pre:
            self.append_text(s)
            return
        for k, piece in enumerate(re.split(f"([{HEAD_END}{FOOT_START}])", s)):
            if piece == HEAD_END:
                self.mark("body")
            elif piece == FOOT_START:
                self.mark("footer")
            elif piece:
                for j, chunk in enumerate(PARAGRAPH.split(piece)):
                    if j:
                        self.paragraph_break()
                    if chunk.strip() or (self.p is not None and chunk):
                        self.append_text(chunk)

    def open_inline(self, tag: str, attrs: dict) -> None:
        cur = self.ensure_p()
        el = etree.SubElement(cur, tag, _attrs(attrs))
        self.inline.append(el)
        self.cursor = el

    def close_inline(self) -> None:
        if self.inline:
            self.inline.pop()
        self.cursor = self.inline[-1] if self.inline else self.p

    def open_block(self, tag: str, attrs: dict | None = None) -> tuple:
        self.paragraph_break()
        el = etree.SubElement(self.container, tag, _attrs(attrs or {}))
        self._top_block(el)
        saved = (self.container, self.p, self.inline, self.cursor)
        self.container, self.p, self.inline, self.cursor = el, None, [], None
        return saved

    def close_block(self, saved: tuple) -> None:
        self.container, self.p, self.inline, self.cursor = saved
        self.paragraph_break()

    def finish(self) -> etree._Element:
        """The document with its top-level blocks in their parts: header, body, footer."""
        for el, _ in self.top:
            self.body.remove(el)
        parts = {"header": etree.Element("header", role="doc-pageheader"), "body": [],
                 "footer": etree.Element("footer", role="doc-pagefooter")}
        for el, where in self.top:
            if where == {"header"}:
                parts["header"].append(el)
            elif where == {"footer"}:
                parts["footer"].append(el)
            else:
                parts["body"].append(el)
        if len(parts["header"]):
            self.body.append(parts["header"])
        for el in parts["body"]:
            self.body.append(el)
        if len(parts["footer"]):
            self.body.append(parts["footer"])
        return self.doc

    # ------------------------------------------------------------------------------------------------ the walk
    def nodes(self, children) -> None:
        for c in children:
            self.node(c)

    def node(self, n) -> None:
        from wikitextprocessor.parser import HTMLNode, NodeKind

        if isinstance(n, str):
            self.text(n)
            return
        k = n.kind
        if isinstance(n, HTMLNode) or k == NodeKind.HTML:
            self.html(n)
        elif k == NodeKind.ITALIC or k == NodeKind.BOLD:
            self.open_inline("i" if k == NodeKind.ITALIC else "b", {})
            self.nodes(n.children)
            self.close_inline()
        elif k in (NodeKind.LEVEL1, NodeKind.LEVEL2, NodeKind.LEVEL3, NodeKind.LEVEL4, NodeKind.LEVEL5,
                   NodeKind.LEVEL6):
            level = int(k.name[-1])
            saved = self.open_block(f"h{level}")
            for arg in n.largs:
                self.nodes(arg)
            self.close_block(saved)
            self.nodes(n.children)                 # a heading's node holds the rest of its section
        elif k == NodeKind.LIST:
            self.list(n)
        elif k == NodeKind.LIST_ITEM:
            self.nodes(n.children)
        elif k == NodeKind.HLINE:
            saved = self.open_block("hr")
            self.close_block(saved)
        elif k == NodeKind.PREFORMATTED or k == NodeKind.PRE:
            self.preformatted(n)
        elif k == NodeKind.LINK:
            self.link(n)
        elif k == NodeKind.URL:
            args = n.largs
            if len(args) > 1:
                for a in args[1:]:
                    self.nodes(a)
            elif args:
                self.nodes(args[0])
        elif k == NodeKind.TABLE:
            self.table(n)
        elif k == NodeKind.MAGIC_WORD:
            return
        elif k in (NodeKind.TEMPLATE, NodeKind.PARSER_FN, NodeKind.TEMPLATE_ARG):
            self.unexpanded.append(_flat(n.largs[0]) if n.largs else k.name)
        else:
            self.nodes(n.children)

    def html(self, n) -> None:
        tag = (n.sarg or "").lower()
        attrs = dict(n.attrs)
        if tag in SILENT:
            return
        if tag == "ref":
            self.ref(n, attrs)
        elif tag in ("math", "chem", "ce"):
            tex = _flat(n.children)
            if tag != "math":
                tex = rf"\ce{{{tex}}}"
            el_attrs = {"alttext": tex}
            if attrs.get("display") == "block":
                el_attrs["display"] = "block"
            self.ensure_p()
            el = etree.SubElement(self.cursor, "math", el_attrs)
            el.tail = ""
        elif tag == "poem":
            self.poem(n, attrs)
        elif tag == "gallery":
            self.gallery(n)
        elif tag == "templatestyles":
            self.style(attrs.get("src", ""))
        elif tag == "nowiki":
            self.text(_flat(n.children))
        elif tag == "br":
            cur = self.ensure_p()
            etree.SubElement(cur, "br")
        elif tag in ("pages", "source", "syntaxhighlight", "hiero"):
            self.text(_flat(n.children))
        elif tag in BLOCK_TAGS:
            saved = self.open_block(tag, attrs)
            self.nodes(n.children)
            self.close_block(saved)
        else:
            self.open_inline(tag if re.match(r"^[a-z][a-z0-9]*$", tag) else "span", attrs)
            self.nodes(n.children)
            self.close_inline()

    def style(self, src: str) -> None:
        """A TemplateStyles style sheet, once per page, as a ``<style>`` element (its scope removed)."""
        if not src or src in self.styles_seen:
            return
        self.styles_seen.add(src)
        css = self.b.styles(src)
        if css:
            st = etree.SubElement(self.body, "style")
            st.text = css.replace(".mw-parser-output", "")

    def ref(self, n, attrs: dict) -> None:
        if not n.children:
            return                                      # a reuse of a named note: no new note
        cls = "mw-ref-follow" if attrs.get("follow") else "mw-ref"
        cur = self.ensure_p()                           # the note stands where its mark is; its content is a
        aside = etree.SubElement(cur, "aside", {"role": "doc-footnote", "class": cls,    # container of its own
                                                **({"data-group": attrs["group"]} if attrs.get("group") else {})})
        saved = (self.container, self.p, self.inline, self.cursor)
        self.container, self.p, self.inline, self.cursor = aside, None, [], None
        self.nodes(n.children)
        self.container, self.p, self.inline, self.cursor = saved

    def list(self, n) -> None:
        from wikitextprocessor.parser import NodeKind

        prefix = n.sarg or "*"
        last = prefix[-1]
        tag = {"*": "ul", "#": "ol", ":": "dl", ";": "dl"}.get(last, "ul")
        saved = self.open_block(tag)
        for item in n.children:
            if not hasattr(item, "kind"):
                continue
            if item.kind == NodeKind.LIST_ITEM:
                itag = {":": "dd", ";": "dt"}.get((item.sarg or prefix)[-1], "li")
                inner = self.open_block(itag)
                self.nodes(item.children)
                self.close_block(inner)
            else:
                self.node(item)
        self.close_block(saved)

    def preformatted(self, n) -> None:
        from wikitextprocessor.parser import NodeKind

        saved = self.open_block("pre")
        self.pre += 1
        for c in n.children:
            if isinstance(c, str):
                self.text(re.sub(r"(^|\n) ", r"\1", c))
            elif c.kind == NodeKind.TABLE:              # wikitextprocessor puts a table after a pre line inside it
                self.pre -= 1
                self.close_block(saved)
                self.node(c)
                saved = self.open_block("pre")
                self.pre += 1
            else:
                self.node(c)
        self.pre -= 1
        self.close_block(saved)

    def link(self, n) -> None:
        args = n.largs
        title = _flat(args[0]) if args else ""
        if self.b.site.file_prefix.match(title) and not title.lstrip().startswith(":"):
            name = re.sub(r"^\s*:?\s*[^:]+:\s*", "", title).strip().replace(" ", "_")
            options = [_flat(a).strip() for a in args[1:]]
            framed = bool(FRAMED & {o.lower() for o in options})
            caption = args[-1] if framed and len(args) > 1 and _flat(args[-1]).strip().lower() not in FRAMED else None
            saved = self.open_block("figure")
            etree.SubElement(self.container, "img", src=f"File:{name}")
            if caption is not None:
                cap = self.open_block("figcaption")
                self.nodes(caption)
                self.close_block(cap)
            self.close_block(saved)
            return
        if self.b.site.hidden_link_prefix.match(title) or re.match(r"^\s*[a-z-]{2,12}\s*:", title) and \
                title.split(":", 1)[0].strip().lower() in INTERWIKI_LANGUAGES:
            return
        if len(args) > 1:
            self.nodes(args[-1])
        else:
            self.text(title.lstrip().lstrip(":"))

    def table(self, n) -> None:
        from wikitextprocessor.parser import NodeKind

        saved = self.open_block("table", dict(n.attrs))
        for c in n.children:
            if not hasattr(c, "kind"):
                continue
            if c.kind == NodeKind.TABLE_CAPTION:
                cap = self.open_block("caption", dict(c.attrs))
                self.nodes(c.children)
                self.close_block(cap)
            elif c.kind == NodeKind.TABLE_ROW:
                row = self.open_block("tr", dict(c.attrs))
                for cell in c.children:
                    if not hasattr(cell, "kind"):
                        continue
                    if cell.kind in (NodeKind.TABLE_CELL, NodeKind.TABLE_HEADER_CELL):
                        tag = "th" if cell.kind == NodeKind.TABLE_HEADER_CELL else "td"
                        inner = self.open_block(tag, dict(cell.attrs))
                        self.nodes(cell.children)
                        self.close_block(inner)
                self.close_block(row)
            else:
                self.node(c)
        self.close_block(saved)

    def poem(self, n, attrs: dict) -> None:
        saved = self.open_block("div", {**attrs, "class": ("poem " + attrs.get("class", "")).strip()})
        body = _flat(n.children) if all(isinstance(c, str) for c in n.children) else None
        if body is None:                                 # formatting inside: lines from the text pieces
            for c in n.children:
                if isinstance(c, str):
                    self._poem_text(c)
                else:
                    self.node(c)
        else:
            self._poem_text(body.strip("\n"))
        self.close_block(saved)

    def _poem_text(self, s: str) -> None:
        stanzas = PARAGRAPH.split(htmllib.unescape(s))
        for j, stanza in enumerate(stanzas):
            if j:
                self.paragraph_break()
            for k, line in enumerate(stanza.split("\n")):
                if k:
                    cur = self.ensure_p()
                    etree.SubElement(cur, "br")
                line = re.sub(r"^:+\s*", "", line)
                if line:
                    self.append_text(line)

    def gallery(self, n) -> None:
        for line in _flat(n.children).splitlines():
            line = line.strip()
            if not line:
                continue
            name, _, caption = line.partition("|")
            name = re.sub(r"^\s*[^:|]+:\s*", "", name).strip().replace(" ", "_")
            saved = self.open_block("figure")
            etree.SubElement(self.container, "img", src=f"File:{name}")
            if caption.strip():
                cap = self.open_block("figcaption")
                self.text(caption.rsplit("|", 1)[-1])
                self.close_block(cap)
            self.close_block(saved)


#: interwiki language prefixes that make a link a language link (printing nothing), for the common languages
INTERWIKI_LANGUAGES = frozenset({"de", "fr", "es", "it", "la", "ru", "pl", "pt", "nl", "sv", "zh", "ja", "el", "he",
                                 "ar", "fa", "cs", "hu", "fi", "da", "no", "ro", "uk", "ca", "ko", "tr"})


def _attrs(attrs: dict) -> dict:
    """Attributes as lxml takes them: string values, names that are XML names."""
    return {k: str(v) for k, v in attrs.items() if re.match(r"^[A-Za-z_][\w.-]*$", str(k))}


def _flat(nodes) -> str:
    """The text of nodes as wikitext prints it, for content that is not wikitext (TeX, a gallery's lines)."""
    out = []
    for n in nodes if isinstance(nodes, list) else [nodes]:
        if isinstance(n, str):
            out.append(n)
        elif hasattr(n, "children"):
            out.append(_flat(n.children))
    return htmllib.unescape("".join(out))
