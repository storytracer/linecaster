"""Matchers: where a rule's match points in a parsed document, one per match kind.

A matcher selects the nodes a match points at (``select``), lists every node coverage counts (``nodes``) and the
features by which an unhandled node is reported (``features``: for a tree its element's classes, for JSON its key).
Nodes are the document's own objects (lxml elements, JSON locations, text spans), so the importer that parsed the
document applies the decisions to them directly.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import cache
from typing import Any, ClassVar, Protocol

from linecaster.markup.model import JsonMatch, TextMatch, TreeMatch


class Matcher[D, N](Protocol):
    """Finds a match kind's matches in a document of type ``D``, as nodes of type ``N``."""

    kind: ClassVar[str]

    def select(self, document: D, match: Any) -> list[N]: ...

    def nodes(self, document: D) -> Iterable[N]: ...

    def features(self, node: N) -> list[str]: ...


@cache
def _css(selector: str, html: bool):
    from lxml.cssselect import CSSSelector

    return CSSSelector(selector, translator="html" if html else "xml")


@dataclass(frozen=True)
class TreeMatcher:
    """CSS selectors on an lxml tree (``html``: HTML's case-insensitive names, else XML's)."""

    html: bool = True
    kind: ClassVar[str] = "tree"

    def select(self, document, match: TreeMatch) -> list:
        found = _css(match.css, self.html)(document)
        if match.text is not None:
            rx = re.compile(match.text)
            found = [e for e in found if rx.search("".join(e.itertext()))]
        if match.style is not None:
            rx = re.compile(match.style, re.I)
            found = [e for e in found if rx.search(e.get("style") or "")]
        if match.inside is not None or match.not_inside is not None:
            inside = set(_css(match.inside, self.html)(document)) if match.inside else None
            outside = set(_css(match.not_inside, self.html)(document)) if match.not_inside else set()
            found = [e for e in found
                     if (inside is None or any(a in inside for a in e.iterancestors()))
                     and not any(a in outside for a in e.iterancestors())]
        return found

    def nodes(self, document) -> Iterator:
        return (e for e in document.iter() if isinstance(e.tag, str))

    def features(self, node) -> list[str]:
        return [f".{c}" for c in (node.get("class") or "").split()]


@dataclass(frozen=True)
class JsonLocation:
    """A matched value of a JSON document: its normalized path and the value."""

    path: str
    value: Any


@dataclass(frozen=True)
class JsonMatcher:
    """JSONPath (RFC 9535) on a parsed JSON document; needs ``jsonpath-rfc9535`` (``linecaster[jsonpath-rfc9535]``)."""

    kind: ClassVar[str] = "json"

    def select(self, document, match: JsonMatch) -> list[JsonLocation]:
        import jsonpath_rfc9535 as jsonpath

        found = [JsonLocation(n.path(), n.value) for n in jsonpath.find(match.path, document)]
        if match.text is not None:
            rx = re.compile(match.text)
            found = [x for x in found if isinstance(x.value, str) and rx.search(x.value)]
        return found

    def nodes(self, document) -> Iterator[JsonLocation]:
        def walk(value, path):
            yield JsonLocation(path, value)
            if isinstance(value, dict):
                for k, v in value.items():
                    yield from walk(v, f"{path}['{k}']")
            elif isinstance(value, list):
                for i, v in enumerate(value):
                    yield from walk(v, f"{path}[{i}]")

        return walk(document, "$")

    def features(self, node: JsonLocation) -> list[str]:
        key = re.search(r"\['([^']*)'\]$", node.path)
        return [key.group(1)] if key else []


@dataclass(frozen=True)
class TextSpan:
    """A matched span of a text: ``[start, end)`` and its text."""

    start: int
    end: int
    text: str


@dataclass(frozen=True)
class TextMatcher:
    """Regular expressions on a text (``re.MULTILINE``); the group ``text``, where the pattern has one, is the
    span."""

    kind: ClassVar[str] = "text"

    def select(self, document: str, match: TextMatch) -> list[TextSpan]:
        out = []
        for m in re.finditer(match.pattern, document, re.MULTILINE):
            g = "text" if "text" in m.re.groupindex else 0
            out.append(TextSpan(m.start(g), m.end(g), m.group(g)))
        return out

    def nodes(self, document: str) -> Iterator[TextSpan]:
        return iter(())

    def features(self, node: TextSpan) -> list[str]:
        return []
