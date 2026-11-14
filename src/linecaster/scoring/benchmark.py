"""The benchmark format (``linecaster.benchmark/1``): how runs are scored against one ground truth. A benchmark
definition is a YAML file in the evaluation's repository; linecaster reads and checks it, and ships none.

A benchmark's hash (``sha256``) covers its functional content: everything but ``description``; evidence records name
it with the benchmark's ``id@edition``, so two records with the same benchmark hash were scored the same way.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..data.sample import listing_sha256
from .lanes import DEFAULT_LANE, LANES
from .render import TEXTS

SCHEMA = "linecaster.benchmark/1"
METRICS = ("cer", "token_recall", "over_extraction", "role_words", "confusion")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Dataset(_Model):
    """The ground truth: where it is and how it is read."""

    repo: str = Field(description="the dataset, repo@revision (a revision always)")
    transcription: str = Field("ground_truth", description="the name of its transcription in the page records")
    importer: str = Field(description="what made the page records from the dataset: a linecaster reader "
                                      "(alto, page, hocr, docling, text, markdown) or the evaluation's own (module:function)")

    @model_validator(mode="after")
    def _revision(self):
        if "@" not in self.repo or not self.repo.split("@", 1)[1]:
            raise ValueError(f"dataset {self.repo!r}: name its revision (repo@revision)")
        return self


class PageSet(_Model):
    """The pages scored: a sample rule (``linecaster.data.sample``) or an explicit list, with its hash."""

    rule: dict | None = Field(None, description="a sample rule: seed, items, per_item, pages")
    ids: list[str] | None = Field(None, description="the page ids, when the set is a list")
    sha256: str = Field(description="sha256:<hex> of the page ids, sorted, one per line (data.sample.listing_sha256)")

    @model_validator(mode="after")
    def _listed(self):
        if self.ids is not None and listing_sha256(self.ids) != self.sha256:
            raise ValueError("pages: sha256 is not the hash of the listed ids")
        return self


class Supports(_Model):
    """What the ground truth has, so that metrics needing what it lacks are not computed."""

    roles: list[str] = Field(default_factory=list, description="the content roles it marks")
    boxes: bool = Field(False, description="its regions have boxes")
    reading_order: bool = Field(False, description="it orders its blocks")
    notes: bool = Field(False, description="it marks notes")
    continuations: bool = Field(False, description="it marks paragraphs continued across pages")


class Bootstrap(_Model):
    seed: int = 0
    resamples: int = Field(1000, ge=0)
    level: float = Field(0.95, gt=0, lt=1)
    over: Literal["items"] = "items"


class Benchmark(_Model):
    """A benchmark definition (``linecaster.benchmark/1``)."""

    schema_: Literal["linecaster.benchmark/1"] = Field(SCHEMA, alias="schema")
    id: str
    edition: int = Field(1, ge=1)
    description: str = ""
    dataset: Dataset
    pages: PageSet
    supports: Supports = Field(default_factory=Supports)
    policy: str = Field("page-layers@1", description="the rendering policy edition both sides are rendered with")
    texts: list[str] = Field(default_factory=lambda: list(TEXTS))
    lanes: list[str] = Field(default_factory=lambda: [DEFAULT_LANE])
    metrics: list[str] = Field(default_factory=lambda: ["cer", "token_recall", "over_extraction"])
    bootstrap: Bootstrap = Field(default_factory=Bootstrap)
    strata: list[str] = Field(default_factory=list, description="page or item fields to report rates by")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def _known(self):
        for name, have, known in (("texts", self.texts, TEXTS), ("lanes", self.lanes, LANES),
                                  ("metrics", self.metrics, METRICS)):
            unknown = set(have) - set(known)
            if unknown:
                raise ValueError(f"{name}: unknown {sorted(unknown)}; known: {sorted(known)}")
        if "role_words" in self.metrics and not self.supports.roles:
            raise ValueError("role_words needs roles the ground truth marks (supports.roles)")
        if "confusion" in self.metrics and not self.supports.boxes:
            raise ValueError("confusion needs a ground truth with boxes (supports.boxes)")
        return self

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.edition}"

    @property
    def sha256(self) -> str:
        content = self.model_dump(mode="json", by_alias=True, exclude={"description"})
        return "sha256:" + hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
