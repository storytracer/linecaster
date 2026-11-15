"""The benchmark format (``linecaster.benchmark/2``): how runs are scored against one ground truth. A benchmark
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
from .counts import UNITS
from .lanes import DEFAULT_LANE, LEGACY, lane, resolve
from .render import TEXTS
from .tokens import WORDS

SCHEMA = "linecaster.benchmark/2"
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
    """A benchmark definition (``linecaster.benchmark/2``): ``benchmark/1`` with the lanes as comparison strategies of
    the catalog, the output strategy both texts are written with, and the unit a character error counts.
    ``read_benchmark`` reads a ``benchmark/1`` as one: its lanes by the strategy that does the same, the unit
    ``codepoint``."""

    schema_: Literal["linecaster.benchmark/2"] = Field(SCHEMA, alias="schema")
    id: str
    edition: int = Field(1, ge=1)
    description: str = ""
    dataset: Dataset
    pages: PageSet
    supports: Supports = Field(default_factory=Supports)
    policy: str = Field("page-layers", description="the rendering policy both sides are rendered with")
    texts: list[str] = Field(default_factory=lambda: list(TEXTS))
    output: str = Field("literal", description="the output strategy both texts are written with (literal: as read)")
    lanes: list[str] = Field(default_factory=lambda: [DEFAULT_LANE], description="the lanes: comparison strategies")
    unit: Literal[UNITS] = Field("grapheme", description="what a character error counts: a grapheme cluster (what a "
                                                         "reader sees as one character) or a code point")
    words: Literal[WORDS] = Field("whitespace", description="the tokenizer of the word metrics (linecaster.scoring."
                                                            "tokens): whitespace, uax29 (Unicode's word boundaries) or "
                                                            "characters")
    metrics: list[str] = Field(default_factory=lambda: ["cer", "token_recall", "over_extraction"])
    bootstrap: Bootstrap = Field(default_factory=Bootstrap)
    strata: list[str] = Field(default_factory=list, description="page or item fields to report rates by")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def _known(self):
        for name, have, known in (("texts", self.texts, TEXTS), ("metrics", self.metrics, METRICS)):
            unknown = set(have) - set(known)
            if unknown:
                raise ValueError(f"{name}: unknown {sorted(unknown)}; known: {sorted(known)}")
        try:
            self.lanes = [lane(x) for x in self.lanes]
        except KeyError as e:
            raise ValueError(f"lanes: {e.args[0]}") from None
        from ..catalog.registry import catalog
        from ..errors import CatalogError

        try:
            written = catalog().strategy(self.output, use="output")      # known, and meant for writing texts
        except CatalogError as e:
            raise ValueError(f"output: {e.args[0]}") from None
        structural = [n.id for n in written.normalizations if not n.text_rule]
        if structural:
            raise ValueError(f"output: {self.output} holds normalizations of a document's structure "
                             f"({', '.join(structural)}), which scoring cannot apply to a page's text")
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
        """The hash of what it does: everything but ``description``, with each lane's and the output strategy's
        hash (a change of a lane in a release changes it); ``words`` only where it is not the default tokenizer."""
        from ..catalog.registry import catalog

        content = self.model_dump(mode="json", by_alias=True, exclude={"description"})
        if content["words"] == "whitespace":
            del content["words"]                               # the default: benchmarks from before keep their hash
        content["lanes"] = [{"id": x, "sha256": resolve(x).sha256} for x in self.lanes]
        content["output"] = {"id": self.output, "sha256": catalog().strategy(self.output, use="output").sha256}
        return "sha256:" + hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def read_benchmark(data: dict) -> Benchmark:
    """A benchmark definition: ``benchmark/2`` as it is, ``benchmark/1`` upgraded (its lanes by the strategy that
    does the same, ``linecaster.scoring.lanes.LEGACY``; the unit ``codepoint``, as it counted)."""
    sid = data.get("schema", "linecaster.benchmark/1")
    if sid == "linecaster.benchmark/1":
        data = {**data, "schema": SCHEMA, "unit": "codepoint",
                "lanes": [LEGACY.get(x, x) for x in data.get("lanes", [DEFAULT_LANE])]}
    elif sid != SCHEMA:
        raise ValueError(f"unknown benchmark format {sid!r}; this linecaster reads benchmark/1 and /2")
    return Benchmark.model_validate(data)
