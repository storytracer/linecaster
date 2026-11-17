"""``SourceFile``: what an importer reads, a file or record of a source with what is known about it."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceFile(BaseModel):
    """One document of a source an importer reads: its content (bytes, or text already decoded), its format where
    known, where it comes from (``uri``, the ``record`` of a table, the ``revision`` its anchors refer to, the
    ``dataset`` it belongs to), the page image's size where the transcription is to fit one, and ``context``: what
    the importer needs besides the content (a wiki page's title, an item's page ids)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    data: bytes | str
    format: str | None = None
    uri: str | None = None
    record: str | None = None
    revision: str | None = None
    dataset: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    context: dict[str, Any] = Field(default_factory=dict)

    def as_bytes(self) -> bytes:
        """The content as bytes (text encoded as UTF-8)."""
        return self.data if isinstance(self.data, bytes) else self.data.encode("utf-8")

    def as_text(self) -> str:
        """The content as text (bytes decoded as UTF-8, a byte order mark dropped)."""
        return self.data if isinstance(self.data, str) else self.data.decode("utf-8-sig")
