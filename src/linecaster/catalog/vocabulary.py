"""The vocabulary entry (``vocabularies/<scheme>.yaml``, ``linecaster.vocabulary``): one classification scheme's closed
list of values, each with its definition, what counts and what does not (``docs/reference/catalog.md``).

A vocabulary is the one text the docs, the taggers and the people who review their answers share: the model tagger's
questions are generated from it, never paraphrased (``linecaster.engines.tagging``), and the data model's tables
agree with it (``tests/catalog/test_vocabularies.py``). A **property scheme** is a yes/no scheme (``degraded``,
``tiny``, ...): its values are ``yes`` and ``no``, the property's definition is the value ``yes``'s, and its
``answers`` name the two answers after the property (``degraded``, ``not_degraded``), so that a model's "yes" cannot
be read as "yes, the marked place is right". An open scheme (``language``, ``script``) has no list of values but a
pattern its values match.

Kept apart from ``linecaster.catalog.schema`` (which lists it among the formats), and importing nothing of linecaster.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: the values of a property scheme, in this order
YES_NO = ("yes", "no")
#: what a scheme classifies, narrowest first (``targets``)
TARGETS = ("span", "word", "line", "region", "page")
#: the answers every question of the model tagger also takes, besides the scheme's: the image does not let the model
#: decide; the marked place holds no content (empty, or the wrong place)
NO_ANSWERS = ("cannot_tell", "not_here")
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class _Doc(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Term(_Doc):
    """One value (or reason) of a vocabulary: what it is, what counts as it and what does not."""

    definition: str = Field(description="what the value means, as one or two sentences that stand on their own")
    counts: list[str] = Field(default_factory=list, description="cases that are this value, each a short phrase")
    does_not_count: list[str] = Field(default_factory=list,
                                      description="cases that are not, though they may look like it, each a short "
                                                  "phrase that names what they are instead where it can")


class VocabularyDoc(_Doc):
    """A classification scheme's vocabulary. Its functional content (hashed in ``catalog.index``) is everything but
    ``description`` and ``provenance``: a definition is what a model tagger is shown, so a changed definition changes
    what it answers."""

    schema_: Literal["linecaster.vocabulary"] = Field(alias="schema")
    scheme: str = Field(description="the classification scheme it defines (linecaster.data.SCHEMES), also its id")
    description: str = Field(description="what the scheme classifies, in a sentence (not functional)")
    targets: list[Literal["span", "word", "line", "region", "page"]] = Field(
        min_length=1, description="what the scheme classifies, narrowest first: span, word, line, region, page")
    values: dict[str, Term] = Field(default_factory=dict, description="the closed list of values, by value")
    open: bool = Field(False, description="the values are not listed: each matches pattern (language, script)")
    pattern: str | None = Field(None, description="an open scheme's values, as a regular expression")
    answers: dict[str, str] = Field(default_factory=dict,
                                    description="a property scheme (values yes and no): the answer that means each "
                                                "value, named after the property (yes: degraded, no: not_degraded)")
    reasons: dict[str, Term] = Field(default_factory=dict,
                                     description="status only: the values of a classification's reason, why "
                                                 "something present in a source is no text of the page")
    provenance: list[str] = Field(default_factory=list,
                                  description="where the definitions come from or what they are adapted from "
                                              "(not functional)")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("scheme")
    @classmethod
    def _scheme(cls, v):
        if not _NAME.match(v):
            raise ValueError(f"schemes are lowercase names with underscores: {v!r}")
        return v

    @model_validator(mode="after")
    def _shape(self):
        if self.open:
            if self.values or self.answers:
                raise ValueError("an open scheme lists no values and no answers")
            if not self.pattern:
                raise ValueError("an open scheme needs a pattern")
            re.compile(self.pattern)
        elif not self.values:
            raise ValueError("a closed scheme lists its values")
        elif self.pattern:
            raise ValueError("a closed scheme has no pattern")
        bad = [v for v in self.values if not _NAME.match(v)]
        if bad:
            raise ValueError(f"values are lowercase names with underscores: {bad}")
        if self.answers:
            if tuple(self.values) != YES_NO or set(self.answers) != set(YES_NO):
                raise ValueError("answers belong to a property scheme: values yes and no, an answer for each")
            names = list(self.answers.values())
            wrong = [a for a in names if not _NAME.match(a) or a in (*YES_NO, *NO_ANSWERS)]
            if wrong or len(set(names)) != 2:
                raise ValueError(f"answers are two distinct names after the property, not yes, no, "
                                 f"{' or '.join(NO_ANSWERS)}: {names}")
        if self.reasons and self.scheme != "status":
            raise ValueError("only status has reasons (Classification.reason)")
        targets = [TARGETS.index(t) for t in self.targets]
        if targets != sorted(set(targets)):
            raise ValueError(f"targets are distinct and narrowest first ({', '.join(TARGETS)}): {self.targets}")
        return self

    @property
    def id(self) -> str:
        """The entry's id: its scheme."""
        return self.scheme

    @property
    def property(self) -> bool:
        """Whether it is a property scheme: yes and no, with answers named after the property."""
        return bool(self.answers)

    def answer_values(self) -> dict[str, str]:
        """The answers a model tagger's question takes -> the value each means: a property scheme's two answers, a
        closed scheme's values as themselves (an open scheme is never asked)."""
        if self.open:
            raise ValueError(f"{self.scheme} is an open scheme: its values are not listed, and it is not asked")
        if self.answers:
            return {a: v for v, a in self.answers.items()}
        return {v: v for v in self.values}

    def functional(self) -> dict:
        """What it does: everything but its description and provenance, as the index hashes it."""
        return self.model_dump(mode="json", by_alias=True, exclude={"description", "provenance"},
                               exclude_defaults=True)
