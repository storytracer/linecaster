"""Decisions: what a convention says a matched thing is, format-neutral and in the data model's vocabulary.

A rule names a decision and gives its fields (``params``); the decision is a small frozen model, so the fields are
checked when the conventions are resolved. Importers apply the decisions they understand (an importer's
``DECISIONS``) to their own nodes; the catalog refuses an entry that uses one its format's importer does not apply.
Engine packages may add decisions through the entry point group ``linecaster.decisions`` (``name = "module:Class"``);
a catalog entry may use only linecaster's and its packages'.
"""
from __future__ import annotations

from functools import cache
from importlib import import_module
from importlib.metadata import entry_points
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..data.policy import ROLES
from ..data.transcription import EDITS, REASONS


def _check_role(v: str) -> str:
    if v not in ROLES:
        raise ValueError(f"role {v!r}: one of {sorted(ROLES)}")
    return v


class Decision(BaseModel):
    """What a matched thing is. ``name`` is how rules refer to it."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: ClassVar[str]


class Remove(Decision):
    """Not text of the page, and why (``REASONS``); ``keep_text``: its text is recorded, as a region with status
    ``removed`` that no text takes, else only counted."""

    name: ClassVar[str] = "remove"
    reason: str
    keep_text: bool = False

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        if v not in REASONS:
            raise ValueError(f"reason {v!r}: one of {sorted(REASONS)}")
        return v


class Invisible(Decision):
    """Printed as nothing, but taking its space: a space where it stands inline, a block break where it is a
    block."""

    name: ClassVar[str] = "invisible"


class Unwrap(Decision):
    """Known and without meaning of its own: its content is read as if it were not there."""

    name: ClassVar[str] = "unwrap"


class Block(Decision):
    """A block of its own, of a content role (``linecaster.data.policy.ROLES``)."""

    name: ClassVar[str] = "block"
    role: str = "paragraph"
    heading_level: int | None = Field(None, ge=1)

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        return _check_role(v)


class Cell(Decision):
    """A cell of a row of cells printed as one line (a running head: left, centre, right): the cells under one
    parent make one region of ``role``, each cell a region of its own inside it."""

    name: ClassVar[str] = "cell"
    role: str = "header"

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        return _check_role(v)


class Picture(Decision):
    """A picture; its file is the value of ``attr`` (or of the first descendant that has it)."""

    name: ClassVar[str] = "picture"
    attr: str = "src"


class Caption(Decision):
    """The caption of the picture or table it belongs to."""

    name: ClassVar[str] = "caption"


class Note(Decision):
    """A note: its text is a region of its own (``footnote``, or ``footnote_continued`` for a note continued from an
    earlier page) linked to the region where it stands (``note_of``); where it stands, nothing is printed."""

    name: ClassVar[str] = "note"
    continued: bool = False


class Edit(Decision):
    """Printed as it is, with another reading of it in an attribute (``corrected``, ``expanded``, ...)."""

    name: ClassVar[str] = "edit"
    kind: Literal["corrected", "normalized", "expanded", "regularized"]
    attr: str = "title"

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in EDITS:
            raise ValueError(f"edit {v!r}: one of {EDITS}")
        return v


class Language(Decision):
    """Text in the language its ``attr`` names (a BCP 47 tag)."""

    name: ClassVar[str] = "language"
    attr: str = "lang"


class Format(Decision):
    """Formatting the data model records (``linecaster.data.Formatting``)."""

    name: ClassVar[str] = "format"
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    script: Literal["baseline", "sub", "super"] = "baseline"


class Break(Decision):
    """The end of a block. At the end of a page: the last paragraph does not run on onto the next page, unless
    ``run_on``."""

    name: ClassVar[str] = "break"
    run_on: bool = False


class Describe(Decision):
    """Not printed: what someone wrote about the page (an image's description, an editor's note), recorded as a
    ``Description`` of the region it stands in; its text is the element's, or ``attr``'s value."""

    name: ClassVar[str] = "describe"
    kind: Literal["description", "data", "note"] = "description"
    attr: str | None = None


#: linecaster's own decisions, by name
DECISIONS: dict[str, type[Decision]] = {c.name: c for c in (Remove, Invisible, Unwrap, Block, Cell, Picture, Caption,
                                                             Note, Edit, Language, Format, Break, Describe)}


@cache
def installed() -> dict[str, type[Decision]]:
    """linecaster's decisions and the installed packages' (entry point group ``linecaster.decisions``)."""
    found = dict(DECISIONS)
    for ep in entry_points(group="linecaster.decisions"):
        module, _, cls = ep.value.partition(":")
        found[ep.name] = getattr(import_module(module), cls)
    return found


def decision_class(name: str) -> type[Decision]:
    """The decision ``name``; an unknown one is a ``KeyError`` naming the known."""
    known = installed()
    if name not in known:
        raise KeyError(f"unknown decision {name!r}; known: {sorted(known)}")
    return known[name]


def make(name: str, params: dict[str, Any]) -> Decision:
    """The decision ``name`` with its fields ``params`` (validated)."""
    return decision_class(name).model_validate(params)
