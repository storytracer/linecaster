"""The conventions format, ``linecaster.conventions/1``: one YAML file per entry (``conventions/<format>/<id>.yaml``
in the catalog), with a mandatory Markdown sidecar (``<id>.md``) for what the rules cannot say.

    schema: linecaster.conventions/1
    id: example
    edition: 2
    format: html                      # what the rules match: the tree, JSON or text the format's importer reads
    extends: base@1                   # one parent, pinned (optional)
    description: ...
    rules:
      - id: running-head-cells        # a parent's id: replaces that rule; a new id: adds one (at the end, or
        match: {kind: tree, css: ".rh-cell"}   # before:/after: a rule id)
        decision: cells
        params: {role: header}        # the decision's fields (linecaster.markup.decisions)
        by: people                    # who made what it records: the source's people (default) or a rule
        why: ...
        decided: 2026-11-12
    disable: {a-parent-rule: "why this source does not use it"}

The models are the only definition of the format; its JSON Schema is generated from them.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator, model_validator

SCHEMA = "linecaster.conventions/1"
#: a rule's or an entry's id
ID = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)


class TreeMatch(_Strict):
    """Elements of an HTML or XML tree: a CSS selector, and optionally conditions on their text, inline style and
    ancestors. Every condition given must hold."""

    kind: Literal["tree"] = "tree"
    css: str = Field(description="a CSS selector (Selectors Level 3, as cssselect reads it)")
    text: str | None = Field(None, description="a regular expression the element's text must match (search)")
    style: str | None = Field(None, description="a regular expression the element's style attribute must match")
    inside: str | None = Field(None, description="a CSS selector one of the element's ancestors must match")
    not_inside: str | None = Field(None, description="a CSS selector none of the element's ancestors may match")


class JsonMatch(_Strict):
    """Values of a JSON document: a JSONPath (RFC 9535), and optionally a regular expression their text must
    match."""

    kind: Literal["json"] = "json"
    path: str = Field(description="a JSONPath query (RFC 9535)")
    text: str | None = Field(None, description="a regular expression a matched string value must match (search)")


class TextMatch(_Strict):
    """Spans of a plain text: a regular expression (Python's ``re``, multiline); a group named ``text``, where the
    pattern has one, is the span the decision is about, else the whole match."""

    kind: Literal["text"] = "text"
    pattern: str = Field(description="a regular expression, searched with re.MULTILINE")

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, v: str) -> str:
        re.compile(v)
        return v


type Match = Annotated[TreeMatch | JsonMatch | TextMatch, Discriminator("kind")]
#: the match kind each format family uses
MATCH_KINDS = ("tree", "json", "text")


class Rule(_Strict):
    """One convention: what it matches, the decision about it, and why."""

    id: str
    match: Match
    decision: str = Field(description="a decision's name (linecaster.markup.decisions.DECISIONS, or a package's)")
    params: dict[str, Any] = Field(default_factory=dict, description="the decision's fields")
    by: Literal["people", "rule"] = Field(
        "people", description="who made what the decision records: the source's people (they marked it) or a rule "
                              "(the conventions infer it)")
    before: str | None = Field(None, description="placed before this rule (where order matters)")
    after: str | None = Field(None, description="placed after this rule (where order matters)")
    why: str = Field(min_length=1)
    decided: str | None = Field(None, description="when, and by whom")
    open: str | None = Field(None, description="what is not settled")

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ID.match(v):
            raise ValueError(f"rule id {v!r}: lowercase letters, digits, '.' and '-'")
        return v

    @field_validator("decided", mode="before")
    @classmethod
    def _date(cls, v):
        return v.isoformat() if isinstance(v, dt.date) else v

    @model_validator(mode="after")
    def _one_place(self):
        if self.before and self.after:
            raise ValueError(f"rule {self.id}: before or after, not both")
        return self


class ConventionsDoc(_Strict):
    """A conventions entry (``linecaster.conventions/1``)."""

    schema_: Literal["linecaster.conventions/1"] = Field(alias="schema")
    id: str
    edition: int = Field(ge=1)
    format: str = Field(description="the format whose importer applies the entry: html, xml, json, text, ...")
    extends: str | None = Field(None, description="the parent entry, id@edition")
    description: str = Field(min_length=1)
    source: dict[str, str] = Field(default_factory=dict,
                                   description="what the entry was written against: the source, its software and "
                                               "versions, the dump or export")
    rules: list[Rule] = Field(default_factory=list)
    disable: dict[str, str] = Field(default_factory=dict, description="a parent's rule id -> why it does not apply")

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.edition}"

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ID.match(v):
            raise ValueError(f"conventions id {v!r}: lowercase letters, digits, '.' and '-'")
        return v

    @field_validator("extends")
    @classmethod
    def _pinned(cls, v: str | None) -> str | None:
        if v is not None and not re.match(r"^[a-z0-9][a-z0-9.\-]*@[1-9][0-9]*$", v):
            raise ValueError(f"extends {v!r}: a pinned edition, id@edition")
        return v

    @model_validator(mode="after")
    def _unique(self):
        ids = [r.id for r in self.rules]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise ValueError(f"{self.id}: rule ids used twice: {dup}")
        if self.disable and not self.extends:
            raise ValueError(f"{self.id}: disable needs a parent (extends)")
        return self
