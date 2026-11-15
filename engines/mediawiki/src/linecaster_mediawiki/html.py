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
``<chem>``/``<ce>`` are MathML ``math`` elements with the TeX in ``alttext`` as MediaWiki's TeX checker writes it
(``linecaster_mediawiki.texvc``) and the TeX as written in an ``annotation`` where it differs; Poem's ``<poem>`` a
``div`` with a line break per line and a paragraph per stanza; Gallery's files pictures with their captions;
TemplateStyles' style sheets ``<style>`` elements (from the wiki's pages, their ``.mw-parser-output`` scope removed);
ProofreadPage's header and footer ``doc-pageheader`` and ``doc-pagefooter``.

Blocks are given to the part of the page their source lies in (the parsed text's markers): a block wholly in the
header is the header's, wholly in the footer the footer's, any other the body's; a paragraph that runs on from the
body into the footer is split there.
"""
from __future__ import annotations

import html as htmllib
import re
from dataclasses import dataclass, field

from lxml import etree

from .proofread import CALL_END, CALL_FIRST, CALL_MARKS, FOOT_START, HEAD_END

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
#: HTML's own elements as wikitext uses them
_HTML_NAMES = (r"div|span|p|center|small|big|font|b|i|u|s|strike|sup|sub|blockquote|section|poem|ref|table|tr|td|th|"
               r"ul|ol|li|dl|dd|dt|h[1-6]|code|tt|em|strong|abbr|cite|q|ins|del")
#: an element's tag that the parser left as text: a closing tag whose element opened on an earlier page (a block
#: opened on one page and closed on another), an opening tag inside a template's argument; MediaWiki's HTML cleanup
#: drops a stray end tag, and the element's text is all that is left to read
STRAY_TAG = re.compile(rf"</?(?:{_HTML_NAMES})(?:\s[^<>]*)?/?>", re.I)
#: the end of a block that opened on an earlier page: the paragraph ends there, as the block's end would end it
STRAY_BLOCK_END = re.compile(r"</(?:div|p|center|blockquote|table|ul|ol|dl|section|poem|h[1-6])\s*>", re.I)
LITERAL_BR = re.compile(r"<br\s*/?\s*/?\s*>", re.I)


@dataclass
class Built:
    """The HTML document and what the build met that it could not read (template calls left unexpanded)."""

    root: etree._Element
    unexpanded: list[str] = field(default_factory=list)
    texvc_rejected: list[str] = field(default_factory=list)
    closes_block: bool = False


class HtmlBuilder:
    """Builds the HTML of one parsed page. ``site`` tells file and category links apart; ``styles(title)`` gives a
    TemplateStyles style sheet's text."""

    def __init__(self, site, styles=None, calls: list | None = None):
        """``calls``: the template calls the parsed text marks (``proofread.mark_calls``): the first element a call
        writes gets its name (``data-mw-template``) and short parameters (``data-mw-param-<name>``), as Parsoid's
        ``data-mw`` records a transclusion, for conventions to match."""
        self.site = site
        self.styles = styles or (lambda title: None)
        self.calls = calls or []
        self.texvc = site.texvc() if hasattr(site, "texvc") else None

    def build(self, root) -> Built:
        w = _Writer(self)
        w.nodes(root.children)
        return Built(w.finish(), w.unexpanded, w.texvc_rejected, w.closes_block)


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
        self.closes_block = False        # the body's last text is followed by the end of a block from an earlier page
        self.block_parts: dict = {}      # every block element -> the parts it is open in
        self.call = None                 # the template call whose output is being read, until its first element
        self.texvc_rejected: list[str] = []
        self.pre = 0
        self.styles_seen: set[str] = set()

    # ------------------------------------------------------------------------------------------------ output
    def _top_block(self, el) -> None:
        if self.container is self.body:
            self.top.append((el, {self.part}))
        else:
            self.top[-1][1].add(self.part) if self.top else None

    def _call_attrs(self, el) -> None:
        """The first element a template call writes: the call's name and short parameters."""
        if self.call is not None:
            name, params = self.call
            el.set("data-mw-template", name)
            for k, v in params.items():
                key = re.sub(r"[^a-z0-9_-]", "-", k.lower())
                if key:
                    el.set(f"data-mw-param-{key}", v)
            self.call = None

    def ensure_p(self) -> etree._Element:
        if self.p is None:
            self.p = etree.SubElement(self.container, "p")
            self._call_attrs(self.p)
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
        if text.strip() and self.part == "body":
            self.closes_block = False
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
        el = self.container                   # every block open here, nested ones too, is open in the next part
        while el is not None and el is not self.body:
            self.block_parts.setdefault(el, set()).add(part)
            el = el.getparent()

    def text(self, s: str) -> None:
        if CALL_MARKS.search(s):                        # a template call starts or ends here
            for piece in CALL_MARKS.split(s):
                if piece == CALL_END:
                    self.call = None
                elif len(piece) == 1 and ord(piece) >= CALL_FIRST:
                    k = ord(piece) - CALL_FIRST
                    self.call = self.b.calls[k] if k < len(self.b.calls) else None
                elif piece:
                    self.text(piece)
            return
        if "templatestyles" in s.lower():               # left as text where wikitextprocessor does not take the tag
            s = TEMPLATESTYLES.sub(lambda m: self.style(m.group(1)) or "", s)
        if "nowiki" in s.lower():                       # an empty <nowiki/> separates wikitext and prints nothing
            s = EMPTY_NOWIKI.sub("", s)
        if "<" in s:                                    # tags the parser left as text (before entities are decoded:
            if LITERAL_BR.search(s):                    # an editor's &lt;div&gt; stays text)
                for k, piece in enumerate(LITERAL_BR.split(s)):
                    if k:
                        etree.SubElement(self.ensure_p(), "br")
                    self.text(piece)
                return
            if STRAY_BLOCK_END.search(s):
                for k, piece in enumerate(STRAY_BLOCK_END.split(s)):
                    if k:
                        self.paragraph_break()
                        self.closes_block = self.closes_block or self.part == "body"
                    self.text(piece)
                return
            s = STRAY_TAG.sub("", s)
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
        self._call_attrs(el)
        self.block_parts[el] = {self.part}
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
        for el, where in self.block_parts.items():
            if len(where) > 1:                         # a block across the parts (the page's own wrapper, or a block
                el.set("data-parts", " ".join(p for p in PARTS if p in where))   # the next or last page goes on with)
        for el, where in list(self.block_parts.items()):
            cells = list(el.iter("td", "th")) if el.tag == "table" and {"header", "footer"} <= where else []
            if len(cells) == 1:                        # the page's frame: a one-cell table the header opens and the
                kids = list(cells[0])                  # footer closes, for the page's own view; its content is the body
                parent = el.getparent()
                if parent is not None:
                    at = parent.index(el)
                    parent.remove(el)
                    for k, kid in enumerate(kids):
                        parent.insert(at + k, kid)
                elif el in parts["body"]:
                    at = parts["body"].index(el)
                    parts["body"][at:at + 1] = kids
        for top in [self.body, *parts["body"], parts["header"], parts["footer"]]:   # a call's mark the parser
            for el in top.iter():                                                   # put where no text is read
                if not isinstance(el.tag, str):
                    continue
                for name in ("text", "tail"):
                    v = getattr(el, name)
                    if v and CALL_MARKS.search(v):
                        setattr(el, name, CALL_MARKS.sub("", v))
                for k, v in el.attrib.items():
                    if CALL_MARKS.search(v):
                        el.set(k, CALL_MARKS.sub("", v))
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
            tex = _unquote(_flat(n.children))
            if tag != "math":
                tex = rf"\ce{{{tex}}}"
            checked = self.b.texvc.check(tex) if self.b.texvc is not None and tex.strip() else None
            if self.b.texvc is not None and tex.strip() and checked is None:
                self.texvc_rejected.append(tex)
            el_attrs = {"alttext": checked or tex}
            if attrs.get("display") == "block":
                el_attrs["display"] = "block"
            self.ensure_p()
            el = etree.SubElement(self.cursor, "math", el_attrs)
            if checked is not None and checked != tex:      # as MediaWiki: alttext texvc's, the TeX as written beside
                semantics = etree.SubElement(el, "semantics")
                etree.SubElement(semantics, "annotation", encoding="application/x-tex").text = tex
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


def _unquote(text: str) -> str:
    """Content of an opaque tag (``site.OPAQUE``) as written: wikitextprocessor's ``<nowiki>`` quoting undone where
    it is left (a template's argument quotes ``_`` as ``&#95;`` past one unescaping)."""
    from wikitextprocessor.common import _nowiki_map

    for ch, entity in _nowiki_map.items():
        text = text.replace(entity, ch)
    return text


def _flat(nodes) -> str:
    """The text of nodes as wikitext prints it, for content that is not wikitext (TeX, a gallery's lines)."""
    out = []
    for n in nodes if isinstance(nodes, list) else [nodes]:
        if isinstance(n, str):
            out.append(n)
        elif hasattr(n, "children"):
            out.append(_flat(n.children))
    return htmllib.unescape("".join(out))
