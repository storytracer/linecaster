"""Items, pages, page images and texts: the rows linecaster's pipelines read and write.

An ``Item`` is any multi-page unit (a book, an issue, a manuscript, a file); a ``Page`` is one of its
pages with its image and any number of named transcriptions (``ocr_original`` from a delivery,
``ocr_new`` from a linecaster run, ``ground_truth``, ...). ``page_id`` is ``item_id`` plus the
page's sequence unless the source has its own stable page ids.

In a datatrove pipeline a page travels as one ``Document``: ``id`` = ``page_id``, ``text`` = the text
of the page's primary transcription, the image bytes in ``media[0]``, and the page row (everything
but the image bytes) under ``metadata["page"]``.
"""
from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .transcription.model import Transcription

PAGE_KEY = "page"


class PageImage(BaseModel):
    """The image a page's coordinates refer to. Bytes travel next to the row (``Document.media``),
    never inside it."""

    model_config = ConfigDict(extra="forbid")

    uri: str | None = None                   # where it was read from
    format: str | None = None                # webp, jpeg, png, jp2, tiff
    width: int | None = None
    height: int | None = None
    sha256: str | None = None                # of the image bytes as stored
    pixels_sha256: str | None = None         # of the decoded pixels (set by conversion blocks)
    source_width: int | None = None          # the master's size when this image is a scaled derivative
    source_height: int | None = None
    scale: float | None = None               # this image's size / the master's size
    decoder: str | None = None               # e.g. "Pillow 13.0.0 / libwebp 1.6.0"
    extra: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()


class Page(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: str
    item_id: str | None = None
    sequence: int | None = None
    image: PageImage | None = None
    transcriptions: dict[str, Transcription] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def transcription(self, name: str) -> Transcription:
        """The named transcription, created empty when missing."""
        if name not in self.transcriptions:
            self.transcriptions[name] = Transcription()
        return self.transcriptions[name]


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Text(BaseModel):
    """One text per item and variant (``verbatim_txt``, ``readable_txt``, ``readable_md``)."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    variant: str
    text: str
    pages: list[str] = Field(default_factory=list)        # page ids in order
    metadata: dict[str, Any] = Field(default_factory=dict)
