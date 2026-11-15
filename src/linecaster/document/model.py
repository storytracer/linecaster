"""The document model (``linecaster.document/2``): a page or an item as a reader reads it, made from its
transcriptions by ``DocumentBuilder`` and written out by the serializers (HTML, Markdown, text, JSON).

The builder's document is literal: each block's text is its lines' readings, rows as laid out (``\n``), the source's
edits as spans next to the text; which of its row breaks are the layout's (``Block.wraps``: rows a recomposition
found to run on, a paragraph continued on the next page) is recorded, not acted on. A transcription strategy writes
the normalized document from it (``linecaster.document.strategy``, the catalog's strategies), and names itself
(``Document.strategy``).

A ``Document`` is its pages and its blocks in reading order. A **block** is one unit of the rendering: a title, a
heading at its level, a paragraph (one across a page break when the pages say it runs on), a list item, a caption,
a note, a page header or footer, a formula, a table, a picture. Each has the content role it was made from
(``linecaster.data.policy.ROLES``), the layer the rendering policy put it in, its text with the formatting over
spans of it, and where it comes from: one ``Origin`` per piece (its page, region, lines, box on the page image and
the characters of the block's text it gives). With sections (``DocumentBuilder(sections=True)``), every block names
the heading whose section it is in.

The JSON (``Document.model_dump_json``, ``to_json``) is the complete document: a reading of it gives the same
serializations again (``from_json``).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..data.transcription import Cell

SCHEMA = "linecaster.document/2"
#: the document formats this linecaster reads (a document/1 as it is: its block texts were flowed, its spans held
#: no edits)
FORMATS = (SCHEMA, "linecaster.document/1")

#: what a block is (from its region's content role: ``block_kind``)
KINDS = ("title", "heading", "paragraph", "list_item", "caption", "footnote", "toc_entry", "reference", "code",
         "page_header", "page_footer", "formula", "table", "picture")
Kind = Literal["title", "heading", "paragraph", "list_item", "caption", "footnote", "toc_entry", "reference", "code",
               "page_header", "page_footer", "formula", "table", "picture"]
#: the layers blocks are in (``linecaster.data.policy.LAYERS`` without ``metadata`` and ``none``: never rendered)
Layer = Literal["body", "furniture", "background", "invisible", "notes"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Span(_Model):
    """Formatting of characters ``[start, end)`` of a block's text."""

    start: int = Field(ge=0)
    end: int = Field(ge=0)
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    script: Literal["baseline", "sub", "super"] = "baseline"
    language: str | None = None
    formula: bool = Field(False, description="the characters are an inline formula, its LaTeX between $ and $")
    edit: Literal["corrected", "joined", "expanded", "regularized"] | None = Field(
        None, description="the source states another reading of the characters (an edit of that kind): edit_text")
    edit_text: str | None = Field(None, description="the edit's text: the correction, the whole word, ...")


class Origin(_Model):
    """One piece of a block: on ``page`` (the document's page number, from 1), from ``region`` and ``lines`` of
    that page's transcription, in ``box`` (``[x0, y0, x1, y1]`` on the page image; None without geometry), giving
    characters ``span`` of the block's text."""

    page: int = Field(ge=1)
    region: str | None = None
    lines: list[str] = Field(default_factory=list)
    box: list[float] | None = None
    span: list[int] = Field(default_factory=lambda: [0, 0])


class Grid(_Model):
    """A table block's structure: its size and cells (``linecaster.data.Cell``: offsets, end exclusive)."""

    num_rows: int
    num_cols: int
    cells: list[Cell] = Field(default_factory=list)


class Block(_Model):
    id: str
    kind: Kind
    role: str | None = None
    layer: Layer = "body"
    level: int | None = None                  # a heading's level (1 the highest below the title)
    text: str = ""                            # lines separated by "\n"; a formula block's text is its LaTeX
    spans: list[Span] = Field(default_factory=list)
    # the offsets of the "\n" in text that are the layout's (rows of running text, a page break inside a paragraph):
    # a strategy's flow joins them; every other "\n" is the text's own (a verse line, a source's line break)
    wraps: list[int] = Field(default_factory=list)
    grid: Grid | None = None
    file: str | None = None                   # a picture's image, as its source names it
    section: str | None = None                # the heading block whose section this block is in
    origins: list[Origin] = Field(default_factory=list)


class Page(_Model):
    page: int = Field(ge=1)
    id: str | None = None                     # the page's id in its item (``<page_id>#<id>`` references)
    width: int | None = None
    height: int | None = None


class Document(_Model):
    schema_: str = Field(SCHEMA, alias="schema")
    name: str = "document"
    producer: str | None = Field(None, description="the linecaster that wrote it (linecaster.data.transcription."
                                                   "producer)")
    strategy: str | None = Field(None, description="the transcription strategy that wrote it: literal as the "
                                                   "builder made it, else a strategy's id or normalizations joined "
                                                   "by +; None: not stated (a linecaster.document/1 file)")

    @field_validator("schema_")
    @classmethod
    def _known(cls, v: str) -> str:
        """A document of another format is refused, not misread (a reader upgrades the formats it knows)."""
        if v not in FORMATS:
            raise ValueError(f"unknown document format {v!r}; this linecaster reads {sorted(FORMATS)}")
        return v
    pages: list[Page] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def layer(self, *layers: str) -> list[Block]:
        """The blocks in ``layers``, in order."""
        return [b for b in self.blocks if b.layer in layers]
