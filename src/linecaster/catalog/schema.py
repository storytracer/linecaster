"""The catalogue's documents as Pydantic models (``specs/catalog.md``): model, preset, evidence, the lock.

Front matter is validated strictly (unknown keys are errors); the Markdown body is kept as ``body``.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: what a step does; ``page`` is end to end (a whole page in, text out)
STEPS = ("layout", "lines", "recognition", "tables", "formulas", "page")
#: OCR-D functional-model steps, for METS agents (``ocrd-tool.json`` ``steps``)
OCRD_STEPS = {
    "layout": "layout/segmentation/region",
    "lines": "layout/segmentation/line",
    "recognition": "recognition/text-recognition",
    "tables": "layout/segmentation/region",
    "formulas": "recognition/text-recognition",
    "page": "recognition/text-recognition",
}
#: what a preset can put into a transcription
PRODUCES = ("regions", "reading_order", "lines", "baselines", "text", "words", "word_confidences",
            "line_confidences", "tables", "formulas", "markdown", "html", "doctags", "layout_json", "latex")
SUPPORT = ("core", "experimental", "legacy")
EVIDENCE_SOURCES = ("own-run", "board", "card-claim", "vendor-benchmark")
RELATIONS = ("mirror", "converted", "quantised", "finetuned")

SLUG = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class _Doc(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------------------------------------- models

class Source(_Doc):
    """Where the files come from. ``kind`` hf: ``ref`` is the repo id; zenodo: the concept DOI; git: the
    repository URL; url: a download URL."""

    kind: Literal["hf", "zenodo", "git", "url"]
    ref: str


class Pin(_Doc):
    """One exact upstream revision of the model, with its files and its card as published then."""

    revision: str = Field(description="the exact identity: commit, version DOI, or the file's sha256")
    tag: str | None = Field(None, description="a tag or branch that pointed at it when pinned; information only")
    doi: str | None = Field(None, description="the version DOI of the same files, where there is one")
    pinned: dt.date
    files: dict[str, str] = Field(default_factory=dict, description="file name -> sha256:<hex>")
    card: str = Field(description="the upstream card, verbatim, relative to the model folder")
    card_sha256: str
    license_file: str | None = Field(None, description="an upstream licence file copied next to the card")

    @field_validator("card_sha256")
    @classmethod
    def _sha(cls, v):
        if not SHA256.match(v):
            raise ValueError("card_sha256 must be sha256:<64 hex>")
        return v

    @field_validator("files")
    @classmethod
    def _files(cls, v):
        bad = [k for k, h in v.items() if not SHA256.match(h)]
        if bad:
            raise ValueError(f"file hashes must be sha256:<64 hex>: {bad}")
        return v


class DerivedFrom(_Doc):
    ref: str = Field(description="what it derives from: a model id, hub repo@revision or DOI")
    relation: Literal["mirror", "converted", "quantised", "finetuned"]


class ModelDoc(_Doc):
    schema_: Literal["linecaster.model/1"] = Field(alias="schema")
    id: str
    version: str | None = Field(None, description="what upstream calls it, verbatim")
    source: Source
    pins: list[Pin] = Field(min_length=1)
    license: str = Field(description="SPDX id where there is one, else the licence's own name")
    languages: list[str] = Field(default_factory=list, description="ISO 639-3")
    scripts: list[str] = Field(default_factory=list, description="ISO 15924")
    params: str | None = None
    derived_from: list[DerivedFrom] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("id")
    @classmethod
    def _id(cls, v):
        if not SLUG.match(v):
            raise ValueError(f"model ids are lowercase slugs: {v!r}")
        return v

    def pin(self, revision: str) -> Pin:
        for p in self.pins:
            if p.revision == revision:
                return p
        raise KeyError(f"{self.id}: no pin {revision!r} (pinned: {[p.revision for p in self.pins]})")


# ------------------------------------------------------------------------------------------------ presets

class ModelRef(_Doc):
    id: str
    revision: str


class EngineRef(_Doc):
    kind: str = Field(description="the engine's versioned kind, e.g. kraken.recognition/1")
    options: dict[str, Any] = Field(default_factory=dict)


class Serve(_Doc):
    """The server a served preset was validated with."""

    server: Literal["vllm", "sglang", "linecaster"]
    version: str | None = None
    image: str | None = Field(None, description="container image with digest, for HF Jobs")
    flags: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class Capabilities(_Doc):
    unit: Literal["line", "region", "page"] | None = None
    produces: list[str] = Field(default_factory=list)

    @field_validator("produces")
    @classmethod
    def _produces(cls, v):
        bad = [x for x in v if x not in PRODUCES]
        if bad:
            raise ValueError(f"unknown capabilities {bad}; known: {PRODUCES}")
        return v


class Provenance(_Doc):
    derived_from: list[str] = Field(default_factory=list,
                                    description="sources of the settings, each at a commit or revision")
    authored_by: list[str] = Field(default_factory=list)
    created: dt.date | None = None


class PresetDoc(_Doc):
    schema_: Literal["linecaster.preset/1"] = Field(alias="schema")
    id: str
    edition: int = Field(ge=1)
    step: Literal["layout", "lines", "recognition", "tables", "formulas", "page"]
    model: ModelRef | None = Field(None, description="None for engines without weights (rules)")
    engine: EngineRef
    settings: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict, description="native label -> DoclingDocument label")
    serve: Serve | None = None
    capabilities: Capabilities = Field(default_factory=Capabilities)
    provenance: Provenance = Field(default_factory=Provenance)
    support: Literal["core", "experimental", "legacy"] = "experimental"
    superseded_by: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("id")
    @classmethod
    def _id(cls, v):
        if not SLUG.match(v):
            raise ValueError(f"preset ids are lowercase slugs: {v!r}")
        return v

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.edition}"


# ----------------------------------------------------------------------------------------------- evidence

class Evidence(_Doc):
    schema_: Literal["linecaster.evidence/1"] = Field(alias="schema")
    preset: str = Field(description="id@edition")
    source: Literal["own-run", "board", "card-claim", "vendor-benchmark"]
    dataset: str = Field(description="repo@revision, or a description for claims")
    metrics: dict[str, float]
    date: dt.date
    hardware: str | None = None
    software: dict[str, str] = Field(default_factory=dict)
    run: str | None = None
    notes: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("preset")
    @classmethod
    def _ref(cls, v):
        if "@" not in v:
            raise ValueError("evidence names an exact preset edition: id@edition")
        return v


# ------------------------------------------------------------------------------------------------- lock

class LockEntry(_Doc):
    sha256: str
    released: dt.date
    linecaster: str | None = Field(None, description="the linecaster commit it was released in")
    resolved: dict[str, Any]


class Lock(_Doc):
    schema_: Literal["linecaster.catalog-lock/1"] = Field("linecaster.catalog-lock/1", alias="schema")
    presets: dict[str, LockEntry] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
