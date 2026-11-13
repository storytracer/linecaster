"""References: strings that name an annotation, or a part of one, in the same annotation set.

======================================  ==========================================================================
``<id>``                                a zone or a range piece on this page
``<line>/<n>``, ``<line>/<n>/<m>``      word ``n`` of the line's reading, glyph ``m`` of that word
``<region>/r<row>c<col>``               the cell of the region's table that starts at that row and column
``<ref>[<start>:<end>]``                characters ``start`` to ``end`` (end exclusive) of the text it names
``""``                                  the page
``<page_id>#<ref>``                     something on another page of the item
======================================  ==========================================================================
"""
from __future__ import annotations

import re
from typing import NamedTuple

_REF = re.compile(r"^(?:(?P<page>[^#]+)#)?(?P<id>[^/\[#]*)"
                  r"(?:/(?:r(?P<row>\d+)c(?P<col>\d+)|(?P<word>\d+)(?:/(?P<glyph>\d+))?))?"
                  r"(?:\[(?P<start>\d+):(?P<end>\d+)\])?$")


class Parsed(NamedTuple):
    page: str | None
    id: str
    word: int | None
    glyph: int | None
    cell: tuple[int, int] | None
    span: tuple[int, int] | None


def parse(ref: str) -> Parsed:
    """The parts of a reference; a string that is none is a ``ValueError``."""
    m = _REF.match(ref)
    if m is None:
        raise ValueError(f"not a reference: {ref!r}")
    n = lambda k: int(m[k]) if m[k] is not None else None          # noqa: E731
    return Parsed(m["page"], m["id"], n("word"), n("glyph"),
                  (n("row"), n("col")) if m["row"] is not None else None,
                  (n("start"), n("end")) if m["start"] is not None else None)


def word(line_id: str, n: int) -> str:
    return f"{line_id}/{n}"


def cell(region_id: str, row: int, col: int) -> str:
    return f"{region_id}/r{row}c{col}"


def span(ref: str, start: int, end: int) -> str:
    return f"{ref}[{start}:{end}]"


def on_page(page_id: str, ref: str) -> str:
    return f"{page_id}#{ref}"


def check_id(value: str) -> str:
    """``value`` if it can be a zone or range id (no ``#``, ``/`` or ``[``), else a ``ValueError``."""
    if any(c in value for c in "#/["):
        raise ValueError(f"an id must not contain '#', '/' or '[': {value!r}")
    return value
