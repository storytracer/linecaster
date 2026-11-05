"""The catalog's entries as Pydantic models (``docs/reference/catalog.md``): model, preset, recipe, evidence, the
lock.

Each is a YAML file, validated strictly (unknown keys are errors); the prose is in a Markdown file next to it,
which tools never read. These models are the only definition of the formats: the JSON Schemas in ``schemas/``
(``<kind>-<n>.json``, named in each file's first line for editors) are generated from them (``json_schemas``,
``linecaster catalog schemas``).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: what a step does; a VLM that reads whole pages is ``recognition`` with ``unit: page``
STEPS = ("layout", "lines", "recognition", "tables", "formulas")
#: OCR-D functional-model steps, for METS agents (``ocrd-tool.json`` ``steps``)
OCRD_STEPS = {
    "layout": "layout/segmentation/region",
    "lines": "layout/segmentation/line",
    "recognition": "recognition/text-recognition",
    "tables": "layout/segmentation/region",
    "formulas": "recognition/text-recognition",
}
#: what a preset can put into a transcription
PRODUCES = ("regions", "reading_order", "lines", "baselines", "text", "words", "word_confidences",
            "line_confidences", "tables", "formulas", "markdown", "html", "doctags", "layout_json", "latex")
SUPPORT = ("core", "experimental", "legacy")
EVIDENCE_SOURCES = ("own-run", "board", "card-claim", "vendor-benchmark")
RELATIONS = ("mirror", "converted", "quantised", "finetuned")

SLUG = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")
#: engines and pipelines are named by a versioned id: kraken.recognition.v1, chat.v1, transcribe_modular.v1
CODE_ID = re.compile(r"^[a-z][a-z0-9_-]*(\.[a-z0-9_-]+)*\.v[0-9]+$")
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


class Serve(_Doc):
    """The server a served preset was validated with."""

    server: Literal["vllm", "sglang", "linecaster"]
    version: str | None = None
    image: str | None = Field(None, description="container image with digest, for HF Jobs")
    flags: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    revision_flag: bool = Field(True, description="pass --revision; false: the server loads the default branch, "
                                                  "checked file by file against the pin")
    pin_ignore: list[str] = Field(default_factory=list, description="globs the default-branch check ignores")
    server_packages: list[list[str]] = Field(default_factory=list,
                                             description="uv pip install argument lists run in the server's Python "
                                                         "first; {repo} and {revision} are the model's")
    draft: dict[str, Any] | None = Field(None, description="speculative decoding: {model: <model id>, revision, "
                                                         "speculative: {...}}")


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
    step: Literal["layout", "lines", "recognition", "tables", "formulas"]
    model: ModelRef | None = Field(None, description="None for engines without weights (rules)")
    submodels: dict[str, ModelRef] = Field(default_factory=dict,
                                           description="further models of a multi-model engine, by role")
    engine: str = Field(description="the code that runs it, by its versioned id, e.g. kraken.recognition.v1")
    options: dict[str, Any] = Field(default_factory=dict, description="the engine's options")
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

    @field_validator("engine")
    @classmethod
    def _engine(cls, v):
        if not CODE_ID.match(v):
            raise ValueError(f"engine ids are versioned, e.g. kraken.recognition.v1: {v!r}")
        return v

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.edition}"

    @property
    def page_preset(self) -> bool:
        """Whether one model reads the whole page (``recognition`` with ``unit: page``; ``launch.py`` runs it)."""
        return self.step == "recognition" and self.capabilities.unit == "page"


# ------------------------------------------------------------------------------------------------ recipes

class RecipeDoc(_Doc):
    """A named, opinionated combination: one pipeline, a preset edition for each of its slots, its options."""

    schema_: Literal["linecaster.recipe/1"] = Field(alias="schema")
    id: str
    edition: int = Field(ge=1)
    pipeline: str = Field(description="the pipeline it fills, by its versioned id, e.g. transcribe_modular.v1 "
                                      "(pipelines/transcribe_modular.py)")
    presets: dict[str, str] = Field(description="slot -> preset id@edition (always an explicit edition)")
    options: dict[str, Any] = Field(default_factory=dict, description="the pipeline's options, by name")
    provenance: Provenance = Field(default_factory=Provenance)
    support: Literal["core", "experimental", "legacy"] = "experimental"
    superseded_by: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("id")
    @classmethod
    def _id(cls, v):
        if not SLUG.match(v):
            raise ValueError(f"recipe ids are lowercase slugs: {v!r}")
        return v

    @field_validator("pipeline")
    @classmethod
    def _pipeline(cls, v):
        if not CODE_ID.match(v):
            raise ValueError(f"pipeline ids are versioned, e.g. transcribe_modular.v1: {v!r}")
        return v

    @field_validator("presets")
    @classmethod
    def _editions(cls, v):
        bad = [f"{k}: {r}" for k, r in v.items() if "@" not in r]
        if bad:
            raise ValueError(f"a recipe names exact preset editions (id@edition): {bad}")
        return v

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.edition}"


# ----------------------------------------------------------------------------------------------- evidence

class Evidence(_Doc):
    schema_: Literal["linecaster.evidence/1"] = Field(alias="schema")
    preset: str | None = Field(None, description="the preset edition measured: id@edition")
    recipe: str | None = Field(None, description="or the recipe edition measured (a whole pipeline): id@edition")
    context: str | None = Field(None, description="for a preset measured inside a pipeline: the rest of it")
    source: Literal["own-run", "board", "card-claim", "vendor-benchmark"]
    dataset: str = Field(description="repo@revision, or a description for claims")
    metrics: dict[str, float]
    date: dt.date
    hardware: str | None = None
    software: dict[str, str] = Field(default_factory=dict)
    run: str | None = None
    notes: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("preset", "recipe")
    @classmethod
    def _ref(cls, v):
        if v is not None and "@" not in v:
            raise ValueError("evidence names an exact edition: id@edition")
        return v

    @model_validator(mode="after")
    def _one(self):
        if (self.preset is None) == (self.recipe is None):
            raise ValueError("evidence measures one preset or one recipe edition")
        return self

    @property
    def subject(self) -> str:
        return self.preset or self.recipe


# ------------------------------------------------------------------------------------------------- lock

class LockEntry(_Doc):
    sha256: str
    previous_sha256: str | None = Field(None, description="the edition's hash before a catalog migration (changes "
                                                          "that keep behavior); run records may name it")
    released: dt.date
    linecaster: str | None = Field(None, description="the linecaster commit it was released in")
    resolved: dict[str, Any]


class Lock(_Doc):
    schema_: Literal["linecaster.lock/2"] = Field("linecaster.lock/2", alias="schema")
    presets: dict[str, LockEntry] = Field(default_factory=dict)
    recipes: dict[str, LockEntry] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------------------------------------- schemas

#: the JSON Schemas' folder, shipped with the package
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
#: every format, by schema id
FORMATS: dict[str, type[BaseModel]] = {
    "linecaster.model/1": ModelDoc,
    "linecaster.preset/1": PresetDoc,
    "linecaster.recipe/1": RecipeDoc,
    "linecaster.evidence/1": Evidence,
    "linecaster.lock/2": Lock,
}


def schema_file(schema_id: str) -> str:
    """``linecaster.preset/1`` -> ``preset-1.json``."""
    kind, _, n = schema_id.removeprefix("linecaster.").partition("/")
    return f"{kind}-{n}.json"


def json_schemas() -> dict[str, str]:
    """File name -> JSON Schema text, generated from the models."""
    out = {}
    for sid, model in FORMATS.items():
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema",
                  **model.model_json_schema(by_alias=True)}
        out[schema_file(sid)] = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    return out


def write_schemas(out: str | Path = SCHEMA_DIR) -> list[Path]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in json_schemas().items():
        (out / name).write_text(text, encoding="utf-8")
        written.append(out / name)
    return written
