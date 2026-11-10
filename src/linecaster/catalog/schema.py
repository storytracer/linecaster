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

from ..errors import CatalogError
from ..runtime.record import RunRecord

#: what a step does; a VLM that reads whole pages is ``recognition`` with ``unit: page``. The first five run models,
#: the others rules (their engines are built in, ``linecaster.engines``)
STEPS = ("layout", "lines", "recognition", "tables", "formulas", "image", "normalization", "typography",
         "recomposition", "composition")
#: the steps whose engines are rules (strategies), in the pipeline's process only
RULE_STEPS = ("image", "normalization", "typography", "recomposition", "composition")
#: OCR-D functional-model steps, for METS agents (``ocrd-tool.json`` ``steps``); steps without one are
#: post-processing (``linecaster.runtime.provenance.OCRD_FALLBACK_STEP``)
OCRD_STEPS = {
    "layout": "layout/segmentation/region",
    "lines": "layout/segmentation/line",
    "recognition": "recognition/text-recognition",
    "tables": "layout/segmentation/region",
    "formulas": "recognition/text-recognition",
    "image": "preprocessing/optimization",
    "typography": "layout/segmentation/classification",
    "composition": "layout/analysis",
}
#: what a preset can put into a transcription
PRODUCES = ("regions", "reading_order", "lines", "baselines", "text", "words", "word_confidences",
            "line_confidences", "tables", "formulas", "markdown", "html", "doctags", "layout_json", "latex")
#: the parts of a page record (or item record) that block contracts name: the page image and record, a library's own
#: transcription file delivered with the page, what presets produce, and what the blocks without a model add
#: (``docs/reference/pipelines.md``)
PARTS = ("image", "metadata", "transcription_file", *PRODUCES, "line_regions", "hierarchy", "nfc", "paragraphs",
         "normalized", "document")
#: what an engine's work is done on, per call (``capabilities.unit``)
UNITS = ("line", "region", "page", "item")
SUPPORT = ("core", "experimental", "legacy")
EVIDENCE_SOURCES = ("own-run", "card-claim", "vendor-benchmark")
RELATIONS = ("mirror", "converted", "quantized", "finetuned")

SLUG = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")
#: engines and pipelines are named by a versioned id: kraken.recognition.v1, chat.v1, transcribe_modular.v1
CODE_ID = re.compile(r"^[a-z][a-z0-9_-]*(\.[a-z0-9_-]+)*\.v[0-9]+$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
#: an ISO 15924 script code (``linecaster.engines.scripts`` checks that Unicode knows it)
SCRIPT_CODE = re.compile(r"^[A-Z][a-z]{3}$")


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
    license_file: str | None = Field(None, description="an upstream license file copied next to the card")

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
    relation: Literal["mirror", "converted", "quantized", "finetuned"]


class ModelDoc(_Doc):
    schema_: Literal["linecaster.model/1"] = Field(alias="schema")
    id: str
    version: str | None = Field(None, description="what upstream calls it, verbatim")
    source: Source
    pins: list[Pin] = Field(min_length=1)
    license: str = Field(description="SPDX id where there is one, else the license's own name")
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
        raise CatalogError(f"{self.id}: no pin {revision!r} (pinned: {[p.revision for p in self.pins]})")


# ------------------------------------------------------------------------------------------------ presets

class ModelRef(_Doc):
    id: str
    revision: str


class Serve(_Doc):
    """The server a served preset was validated with: a chat server, ``linecaster serve``, or the service a page
    engine talks to (vLLM for an engine package that attaches to it, a vendor's own image entrypoint)."""

    server: Literal["vllm", "sglang", "linecaster", "vendor"]
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
    command: list[str] = Field(default_factory=list, description="vendor: the image's entrypoint, the command that "
                                                                  "starts the service")
    health: list[str] = Field(default_factory=list, description="vendor: loopback URLs that each answer 200 once the "
                                                                "service is ready, in order")
    weights_dir: str | None = Field(None, description="vendor: the folder the entrypoint reads the weights from; the "
                                                      "model pin is downloaded there first")


class Capabilities(_Doc):
    unit: Literal["line", "region", "page", "item"] | None = None
    produces: list[str] = Field(default_factory=list, description="parts it adds (PARTS): what a model produces, "
                                                                  "or what a rule-based step adds")

    @field_validator("produces")
    @classmethod
    def _produces(cls, v):
        bad = [x for x in v if x not in PARTS]
        if bad:
            raise ValueError(f"unknown capabilities {bad}; known: {PARTS}")
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
    step: Literal["layout", "lines", "recognition", "tables", "formulas", "image", "normalization", "typography",
                  "recomposition", "composition"]
    model: ModelRef | None = Field(None, description="None for engines without weights (rules)")
    submodels: dict[str, ModelRef] = Field(default_factory=dict,
                                           description="further models of a multi-model engine, by role")
    engine: str = Field(description="the code that runs it, by its versioned id, e.g. kraken.recognition.v1")
    options: dict[str, Any] = Field(default_factory=dict, description="the engine's options")
    settings: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict, description="native label -> DoclingDocument label")
    by_script: dict[str, str] = Field(default_factory=dict,
                                      description="a by-script engine's strategies: ISO 15924 script code, or * for "
                                                  "every other script (required) -> preset id@edition of the same "
                                                  "step")
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

    @field_validator("by_script")
    @classmethod
    def _by_script(cls, v):
        if not v:
            return v
        bad = [k for k in v if k != "*" and not SCRIPT_CODE.match(k)]
        if bad:
            raise ValueError(f"by_script keys are ISO 15924 script codes (Latn, Hebr) or '*': {bad}")
        if "*" not in v:
            raise ValueError("by_script needs a default strategy: '*'")
        loose = [f"{k}: {r}" for k, r in v.items() if "@" not in r]
        if loose:
            raise ValueError(f"by_script names exact preset editions (id@edition): {loose}")
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
    """One measurement of a preset or recipe edition, with its source. linecaster's catalog holds no evidence
    records (it is not a data repository): the format is for evaluations kept elsewhere, in a derivative's or an
    evaluation's own repository, which name what they measured by edition and hash."""

    schema_: Literal["linecaster.evidence/1"] = Field(alias="schema")
    preset: str | None = Field(None, description="the preset edition measured: id@edition")
    recipe: str | None = Field(None, description="or the recipe edition measured (a whole pipeline): id@edition")
    context: str | None = Field(None, description="for a preset measured inside a pipeline: the rest of it")
    source: Literal["own-run", "card-claim", "vendor-benchmark"]
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
    previous_sha256: str | list[str] | None = Field(
        None, description="the edition's hash before a catalog migration (changes that keep behavior), or its hashes "
                          "before several, oldest first; run records may name them")
    released: dt.date
    linecaster: str | None = Field(None, description="the linecaster commit it was released in")
    resolved: dict[str, Any]
    pipeline: list[dict[str, Any]] | None = Field(None, description="a recipe edition: its expanded pipeline, every "
                                                                    "block with its functional parameters")
    pipeline_sha256: str | None = Field(None, description="a recipe edition: the hash of its expanded pipeline, as "
                                                          "run records name it")

    @property
    def previous(self) -> tuple[str, ...]:
        """The edition's earlier hashes, oldest first."""
        p = self.previous_sha256
        return () if p is None else (p,) if isinstance(p, str) else tuple(p)


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
    "linecaster.run-record/1": RunRecord,
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
