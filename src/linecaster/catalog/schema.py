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

from ..data.page import PAGE_SCHEMA, Page
from ..data.policy import RenderingPolicy
from ..document.model import SCHEMA as DOCUMENT_SCHEMA, Document
from ..markup.model import ConventionsDoc
from ..scoring.benchmark import Benchmark
from ..errors import CatalogError
from ..runtime.record import RunRecord

#: what a step does; a VLM that reads whole pages is ``recognition`` with ``unit: page``. The first five run models,
#: the others rules (their engines are built in, ``linecaster.engines``, or come with an engine package); ``import``
#: reads a source document (a transcription file, a source's markup) into a transcription
STEPS = ("layout", "lines", "recognition", "tables", "formulas", "image", "typography", "recomposition", "composition",
         "import")
#: the steps whose engines are rules (strategies), in the pipeline's process only
RULE_STEPS = ("image", "typography", "recomposition", "composition", "import")
#: OCR-D functional-model steps, for METS agents (``ocrd-tool.json`` ``steps``); steps without one are
#: post-processing (``linecaster.runtime.provenance.OCRD_FALLBACK_STEP``)
OCRD_STEPS = {
    "layout": "layout/segmentation/region",
    "lines": "layout/segmentation/line",
    "assignment": "layout/segmentation/line",          # the line assigner: detected lines into the layout's regions
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
PARTS = ("image", "metadata", "transcription_file", *PRODUCES, "line_regions", "hierarchy", "paragraphs", "document")
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
    schema_: Literal["linecaster.model"] = Field(alias="schema")
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


#: the vLLM release linecaster runs its presets on: a vLLM preset that names no ``serve.version`` gets it (a preset
#: names another version only where this one fails it)
VLLM_VERSION = "0.30.0"
#: a vLLM release's image, for a preset that names no ``serve.image``
VLLM_IMAGE = "vllm/vllm-openai:v{version}"


class Serve(_Doc):
    """The server a served preset runs on: a chat server, ``linecaster serve``, or the service a page engine talks to
    (vLLM for an engine package that attaches to it, a vendor's own image entrypoint). vLLM's version defaults to
    linecaster's (``VLLM_VERSION``), its image to that release's ``vllm/vllm-openai`` image."""

    server: Literal["vllm", "sglang", "linecaster", "vendor"]
    version: str | None = Field(None, description=f"the server's release; vLLM: linecaster's ({VLLM_VERSION}) "
                                                  "unless the preset names another")
    image: str | None = Field(None, description="container image, for HF Jobs; vLLM: the release's "
                                                "vllm/vllm-openai image unless the preset names another")
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

    @model_validator(mode="after")
    def _vllm_default(self):
        if self.server == "vllm":
            self.version = self.version or VLLM_VERSION
            if self.image is None and re.fullmatch(r"\d+\.\d+\.\d+", self.version):
                self.image = VLLM_IMAGE.format(version=self.version)
        return self


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
    schema_: Literal["linecaster.preset"] = Field(alias="schema")
    id: str
    step: Literal[STEPS]
    model: ModelRef | None = Field(None, description="None for engines without weights (rules)")
    submodels: dict[str, ModelRef] = Field(default_factory=dict,
                                           description="further models of a multi-model engine, by role")
    engine: str = Field(description="the code that runs it, by its versioned id, e.g. kraken.recognition.v1")
    options: dict[str, Any] = Field(default_factory=dict, description="the engine's options")
    settings: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict, description="native label -> region label")
    by_script: dict[str, str] = Field(default_factory=dict,
                                      description="a by-script engine's strategies: ISO 15924 script code, or * for "
                                                  "every other script (required) -> the preset (its id) of the "
                                                  "same step")
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
        pinned = [f"{k}: {r}" for k, r in v.items() if "@" in r]
        if pinned:
            raise ValueError(f"by_script names presets by id (catalog entries carry no edition): {pinned}")
        return v

    @property
    def ref(self) -> str:
        return self.id

    @property
    def page_preset(self) -> bool:
        """Whether one model reads the whole page (``recognition`` with ``unit: page``; ``launch.py`` runs it)."""
        return self.step == "recognition" and self.capabilities.unit == "page"


# ------------------------------------------------------------------------------------------------ policies

class PolicyDoc(RenderingPolicy):
    """A rendering policy as a catalog entry (``policies/<id>.yaml``): which annotations go into which layer of a
    rendering, and whose count where several annotators gave one (``linecaster.data.policy.RenderingPolicy``).
    Its functional content is everything but ``description``."""

    schema_: Literal["linecaster.policy"] = Field(alias="schema")
    description: str = Field("", description="what the policy is for (not part of its functional content)")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def policy(self) -> RenderingPolicy:
        return RenderingPolicy(**self.model_dump(exclude={"schema_", "description"}))


# ------------------------------------------------------------------------------------------------ recipes

class RecipeDoc(_Doc):
    """A named, opinionated combination: one pipeline, a preset for each of its slots, its options."""

    schema_: Literal["linecaster.recipe"] = Field(alias="schema")
    id: str
    pipeline: str = Field(description="the pipeline it fills, by its versioned id, e.g. transcribe_modular.v1 "
                                      "(pipelines/transcribe_modular.py)")
    presets: dict[str, str] = Field(description="slot -> preset id")
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
    def _ids(cls, v):
        bad = [f"{k}: {r}" for k, r in v.items() if "@" in r]
        if bad:
            raise ValueError(f"a recipe names its presets by id (catalog entries carry no edition): {bad}")
        return v

    @property
    def ref(self) -> str:
        return self.id


# ------------------------------------------------------------------------------- normalizations, strategies

#: what a normalization is for: writing a text, comparing two (casefolding, dropping punctuation), or both
USES = ("output", "comparison")
#: the rules a normalization may hold, exactly one each: on characters (``text``), or on a document's structure
#: (the source's edits, divided words, division marks, flow)
TEXT_RULES = ("unicode", "map", "patterns", "case", "keep", "whitespace", "latex")
STRUCTURE_RULES = ("edits", "divided_words", "division_marks", "flow")


class Pattern(_Doc):
    match: str = Field(description="a regular expression (Python's re)")
    flags: list[Literal["I", "M", "S"]] = Field(default_factory=list, description="re flags: I, M, S")
    replace: str = Field(" ", description="what a match becomes")

    @field_validator("match")
    @classmethod
    def _compiles(cls, v):
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"pattern {v!r}: {e}") from None
        return v


class Keep(_Doc):
    """The characters kept; every run of others becomes one space."""

    categories: list[Literal["L", "M", "N", "P", "S", "Z", "C"]] = Field(
        default_factory=list, description="Unicode general categories (by their first letter)")
    ranges: list[str] = Field(default_factory=list, description="character ranges, e.g. a-z, 0-9")
    also: str = Field("", description="further characters kept, e.g. U+FFFD (an illegible character)")


class Rule(_Doc):
    """A normalization's rule: exactly one field set."""

    unicode: Literal["NFC", "NFKC"] | None = Field(None, description="a Unicode normalization form")
    map: dict[str, str] | None = Field(None, description="a table: each key (a character or a sequence; the longest "
                                                         "first) becomes its value ('' removes it)")
    patterns: list[Pattern] | None = Field(None, description="regular expressions, applied in order")
    case: Literal["fold", "lower"] | None = Field(None, description="Unicode case folding, or lowercasing")
    keep: Keep | None = Field(None, description="only these characters; every run of others one space")
    whitespace: Literal["collapse"] | None = Field(None, description="every run of whitespace one space, trimmed")
    latex: Literal["text"] | None = Field(None, description="each LaTeX formula as the characters it prints "
                                                       "(linecaster.text.latex), for comparison")
    edits: list[Literal["corrected", "expanded", "regularized"]] | None = Field(
        None, description="the source's own edits of these kinds, applied (a document's edit spans)")
    divided_words: Literal["source"] | None = Field(
        None, description="a word divided across lines or pages, joined where the source marks it (joined edits)")
    division_marks: Literal["unicode-marks"] | None = Field(
        None, description="a named method resolving the division marks no source marked")
    flow: bool | None = Field(None, description="a block's rows joined into running text")

    @model_validator(mode="after")
    def _one(self):
        set_ = [k for k in (*TEXT_RULES, *STRUCTURE_RULES) if getattr(self, k) is not None]
        if len(set_) != 1:
            raise ValueError(f"a normalization holds exactly one rule ({', '.join((*TEXT_RULES, *STRUCTURE_RULES))}); "
                             f"this one: {set_ or 'none'}")
        return self

    @property
    def kind(self) -> str:
        return next(k for k in (*TEXT_RULES, *STRUCTURE_RULES) if getattr(self, k) is not None)


class NormalizationDoc(_Doc):
    """One named normalization (``normalizations/<id>.yaml``): one concern, one rule, applied when a text is written
    or two are compared, never stored in a record."""

    schema_: Literal["linecaster.normalization"] = Field(alias="schema")
    id: str
    description: str = Field(min_length=1)
    scripts: list[str] = Field(default_factory=lambda: ["*"], description="ISO 15924 codes it is meant for, * any")
    languages: list[str] = Field(default_factory=list, description="BCP 47 tags it is meant for (empty: none in "
                                                                   "particular); a language-specific one is never "
                                                                   "applied unless named")
    use: list[Literal[USES]] = Field(description="output, comparison, or both")
    subsumes: list[str] = Field(default_factory=list, description="normalizations whose effect this one includes "
                                                                  "(nfkc: ligatures, long-s), for the ground truth's "
                                                                  "conventions check")
    rule: Rule

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("id")
    @classmethod
    def _id(cls, v):
        if not SLUG.match(v) or v == "literal":
            raise ValueError(f"normalization ids are lowercase slugs, not 'literal': {v!r}")
        return v


class StrategyDoc(_Doc):
    """A transcription strategy (``strategies/<id>.yaml``): an ordered list of normalizations, for writing texts or
    comparing them (a lane). ``literal`` is the built-in strategy without any."""

    schema_: Literal["linecaster.strategy"] = Field(alias="schema")
    id: str
    description: str = Field(min_length=1)
    use: Literal[USES] = Field(description="output (a text written) or comparison (a lane)")
    normalizations: list[str] = Field(description="the normalizations by id, in the order they apply")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("id")
    @classmethod
    def _id(cls, v):
        if not SLUG.match(v) or v == "literal":
            raise ValueError(f"strategy ids are lowercase slugs, not 'literal' (built in): {v!r}")
        return v


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
        return v                  # an id; records from before 0.10 name id@edition (kept as written)

    @model_validator(mode="after")
    def _one(self):
        if (self.preset is None) == (self.recipe is None):
            raise ValueError("evidence measures one preset or one recipe edition")
        return self

    @property
    def subject(self) -> str:
        return self.preset or self.recipe


class EvidenceRun(_Doc):
    """The run an evidence record measured: where its run folder is, and the hashes that name what ran."""

    uri: str | None = Field(None, description="the run folder (OUT)")
    run_id: str | None = Field(None, description="the run record's run_id, stamped on every annotator it added")
    pipeline_sha256: str | None = Field(None, description="the run record's pipeline_sha256")
    record_sha256: str | None = Field(None, description="sha256 of the run record file (run.yaml)")


class EvidenceBenchmark(_Doc):
    ref: str = Field(description="the benchmark edition: id@edition")
    sha256: str = Field(description="the benchmark's hash (linecaster.scoring.benchmark.Benchmark.sha256)")


class EvidenceScoring(_Doc):
    """How the run was scored: two records are comparable when these and the benchmark are the same."""

    policy: str = Field(description="the rendering policy edition both sides were rendered with")
    lanes: list[str] = Field(description="the lane editions")
    scorer: str = Field(description="linecaster's scorer (linecaster-scorer@1 before 0.10)")
    linecaster: str | None = Field(None, description="the linecaster version and commit that scored")


class Metric(_Doc):
    value: float | None
    lo: float | None = None
    hi: float | None = None
    n: int | None = Field(None, description="the pages it was computed over")


class EvidenceHardware(_Doc):
    gpu: list[str] = Field(default_factory=list)
    gpu_count: int | None = None
    driver: str | None = None
    cuda: str | None = None
    cpu: str | None = None
    machine: str | None = None


class Evidence2(_Doc):
    """One measurement of a preset or recipe edition (``linecaster.evidence/2``): ``evidence/1`` with the run, the
    benchmark and the scoring named structurally, metrics with their intervals, the hardware as fields. Kept by an
    evaluation, never in linecaster's catalog."""

    schema_: Literal["linecaster.evidence/2"] = Field(alias="schema")
    preset: str | None = Field(None, description="the preset edition measured: id@edition")
    recipe: str | None = Field(None, description="or the recipe edition measured: id@edition")
    context: str | None = Field(None, description="for a preset measured inside a pipeline: the rest of it")
    source: Literal["own-run", "card-claim", "vendor-benchmark"]
    run: EvidenceRun | None = None
    benchmark: EvidenceBenchmark | None = Field(None, description="the benchmark it was scored by (own runs)")
    dataset: str | None = Field(None, description="for claims without a benchmark: repo@revision or a description")
    scoring: EvidenceScoring | None = None
    metrics: dict[str, Metric]
    counts: dict[str, int] = Field(default_factory=dict, description="pages scored, missing, failed, ...")
    date: dt.date
    hardware: EvidenceHardware | None = None
    software: dict[str, str] = Field(default_factory=dict)
    notes: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    _ref = field_validator("preset", "recipe")(Evidence._ref.__func__)

    @model_validator(mode="after")
    def _one(self):
        if (self.preset is None) == (self.recipe is None):
            raise ValueError("evidence measures one preset or one recipe edition")
        if self.source == "own-run" and (self.benchmark is None or self.scoring is None):
            raise ValueError("an own run's evidence names its benchmark and its scoring")
        return self

    @property
    def subject(self) -> str:
        return self.preset or self.recipe

    def comparable(self, other: "Evidence2") -> bool:
        """Scored the same way: the same benchmark (hash), policy, lanes and scorer."""
        return (self.benchmark is not None and other.benchmark is not None
                and self.benchmark.sha256 == other.benchmark.sha256 and self.scoring is not None
                and other.scoring is not None and (self.scoring.policy, self.scoring.lanes, self.scoring.scorer)
                == (other.scoring.policy, other.scoring.lanes, other.scoring.scorer))


class Named(_Doc):
    """A catalog entry as a score names it: its id and the hash of its functional content (``None`` in a record
    upgraded from before 0.10, which named an edition)."""

    id: str
    sha256: str | None = None


class Words(_Doc):
    """How the word metrics (recall, over-extraction, role words) cut a text into words."""

    tokenizer: Literal["whitespace", "uax29", "characters"] = Field("whitespace", description="linecaster.scoring."
                                                                                               "tokens")
    version: int = Field(1, description="the version of the word metrics' rules (linecaster.scoring.WORDS_VERSION): "
                                        "1 dropped combining marks, 2 keeps them in their words")


class EvidenceScoring3(_Doc):
    """How the run was scored: two records are comparable when these (every hash known) and the benchmark agree."""

    policy: Named = Field(description="the rendering policy both sides were rendered with")
    output: Named = Field(description="the output strategy both texts were written with (literal: as read)")
    lanes: list[Named] = Field(description="the lanes (comparison strategies)")
    unit: Literal["grapheme", "codepoint"] = Field(description="what a character error counts")
    words: Words | None = Field(None, description="the word metrics' tokenizer and the version of their rules; absent "
                                                  "(records from before 0.11): whitespace, version 1")
    scorer: str = Field(description="the linecaster that scored (linecaster.scoring.scorer())")


class EvidenceSlice(_Doc):
    """The rates of a run on one slice of a benchmark's pages (``linecaster.scoring.slices``)."""

    definition: str = Field(description="what puts a page in the slice")
    pages: int = Field(description="the benchmark's pages in it")
    metrics: dict[str, Metric]

    model_config = ConfigDict(extra="forbid")


class Evidence3(_Doc):
    """One measurement of a preset or recipe (``linecaster.evidence/3``): ``evidence/2`` with entries named by id and
    hash (the release versions the catalog), the scoring's output strategy, lanes and unit. Kept by an evaluation,
    never in linecaster's catalog. An ``evidence/2`` record is read as one (``read_evidence``), its lanes by name and
    its unit ``codepoint``, without the hashes that make it comparable to records written since."""

    schema_: Literal["linecaster.evidence/3"] = Field(alias="schema")
    preset: str | None = Field(None, description="the preset measured, by id (id@edition before 0.10)")
    recipe: str | None = Field(None, description="or the recipe measured, by id")
    sha256: str | None = Field(None, description="its hash in the release that ran it (the run record's)")
    context: str | None = Field(None, description="for a preset measured inside a pipeline: the rest of it")
    source: Literal["own-run", "card-claim", "vendor-benchmark"]
    run: EvidenceRun | None = None
    benchmark: EvidenceBenchmark | None = Field(None, description="the benchmark it was scored by (own runs)")
    dataset: str | None = Field(None, description="for claims without a benchmark: repo@revision or a description")
    scoring: EvidenceScoring3 | None = None
    metrics: dict[str, Metric]
    slices: dict[str, EvidenceSlice] = Field(default_factory=dict, description="the rates on slices of the pages: "
                                             "those with tables, formulas, neither (linecaster.scoring.slices)")
    counts: dict[str, int] = Field(default_factory=dict, description="pages scored, missing, failed, ...")
    date: dt.date
    hardware: EvidenceHardware | None = None
    software: dict[str, str] = Field(default_factory=dict)
    notes: str | None = None
    upgraded_from: str | None = Field(None, description="the format it was read from (an older record, upgraded)")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def _one(self):
        if (self.preset is None) == (self.recipe is None):
            raise ValueError("evidence measures one preset or one recipe")
        if self.source == "own-run" and (self.benchmark is None or self.scoring is None):
            raise ValueError("an own run's evidence names its benchmark and its scoring")
        return self

    @property
    def subject(self) -> str:
        return self.preset or self.recipe

    def comparable(self, other: "Evidence3") -> bool:
        """Scored the same way: the same benchmark (hash), policy, output strategy, lanes (by hash), unit and word
        metrics (tokenizer and rules); a record with a hash missing (upgraded from evidence/2) is comparable to
        none."""
        def key(e):
            sc = e.scoring
            named = [sc.policy, sc.output, *sc.lanes] if sc else []
            if e.benchmark is None or sc is None or any(n.sha256 is None for n in named):
                return None
            words = sc.words or Words()
            return (e.benchmark.sha256, *((n.id, n.sha256) for n in named), sc.unit, words.tokenizer, words.version)
        a, b = key(self), key(other)
        return a is not None and a == b


def upgrade_evidence_2(data: dict) -> dict:
    """An ``evidence/2`` record as ``evidence/3``: lanes by their strategy (``linecaster.scoring.lanes.LEGACY``),
    the unit ``codepoint``, the output ``literal``, no hashes (it is comparable to no record written since)."""
    from ..scoring.lanes import LEGACY

    out = {k: v for k, v in data.items() if k != "schema"}
    out["schema"] = "linecaster.evidence/3"
    out["upgraded_from"] = "linecaster.evidence/2"
    sc = data.get("scoring")
    if sc:
        out["scoring"] = {"policy": {"id": sc["policy"].split("@", 1)[0]}, "output": {"id": "literal"},
                          "lanes": [{"id": LEGACY.get(x, x.split("@", 1)[0])} for x in sc.get("lanes", [])],
                          "unit": "codepoint", "scorer": sc.get("scorer", "")}
    return out


def read_evidence(data: dict) -> Evidence | Evidence3:
    """An evidence record, by its ``schema``: ``evidence/3`` as it is, ``evidence/2`` upgraded to it; ``evidence/1``
    (claims, no scoring) as it is."""
    sid = data.get("schema")
    if sid == "linecaster.evidence/3":
        return Evidence3.model_validate(data)
    if sid == "linecaster.evidence/2":
        Evidence2.model_validate(data)                       # a valid evidence/2, or the error says why not
        return Evidence3.model_validate(upgrade_evidence_2(data))
    if sid == "linecaster.evidence/1":
        return Evidence.model_validate(data)
    raise ValueError(f"unknown evidence format {sid!r}; this linecaster reads evidence/1, /2 and /3")


# ---------------------------------------------------------------------------------------------- schemas

#: the JSON Schemas' folder, shipped with the package
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
#: every format, by schema id
FORMATS: dict[str, type[BaseModel]] = {
    "linecaster.model": ModelDoc,
    "linecaster.preset": PresetDoc,
    "linecaster.recipe": RecipeDoc,
    "linecaster.policy": PolicyDoc,
    "linecaster.conventions": ConventionsDoc,
    "linecaster.normalization": NormalizationDoc,
    "linecaster.strategy": StrategyDoc,
    "linecaster.evidence/1": Evidence,
    "linecaster.evidence/2": Evidence2,
    "linecaster.evidence/3": Evidence3,
    "linecaster.benchmark/2": Benchmark,
    "linecaster.run-record/1": RunRecord,
    PAGE_SCHEMA: Page,                   # a page record's `page` (the row: schema, id, text, page, errors)
    DOCUMENT_SCHEMA: Document,
}


def schema_file(schema_id: str) -> str:
    """``linecaster.preset`` -> ``preset.json`` (a catalog file, versioned by the release);
    ``linecaster.evidence/2`` -> ``evidence-2.json`` (a data format, with its own version)."""
    kind, _, n = schema_id.removeprefix("linecaster.").partition("/")
    return f"{kind}-{n}.json" if n else f"{kind}.json"


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
