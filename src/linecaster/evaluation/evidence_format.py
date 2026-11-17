"""The evidence record's formats (``linecaster.evidence/1`` to ``/3``) as pydantic models: one measurement of a preset
or recipe with its source, the run, the benchmark and the scoring it was measured with. Evidence records are kept by
evaluations in their own repositories; linecaster holds the format, reads every version (``read_evidence``) and
writes the current one (``linecaster.evaluation.evidence``)."""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from linecaster.catalog.schema import EVIDENCE_SOURCES, _Doc

class Evidence(_Doc):
    """One measurement of a preset or recipe edition, with its source. linecaster's catalog holds no evidence
    records (it is not a data repository): the format is for evaluations kept elsewhere, in a downstream project's or an
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
    sha256: str = Field(description="the benchmark's hash (linecaster.evaluation.benchmark.Benchmark.sha256)")


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

    tokenizer: Literal["whitespace", "uax29", "characters"] = Field("whitespace", description="linecaster.evaluation."
                                                                                               "tokens")
    version: int = Field(1, description="the version of the word metrics' rules (linecaster.evaluation.WORDS_VERSION): "
                                        "1 dropped combining marks, 2 keeps them in their words")


class EvidenceScoring3(_Doc):
    """How the run was scored: two records are comparable when these (every hash known) and the benchmark agree."""

    policy: Named = Field(description="the rendering policy both sides were rendered with")
    output: Named = Field(description="the output strategy both texts were written with (literal: as read)")
    lanes: list[Named] = Field(description="the lanes (comparison strategies)")
    unit: Literal["grapheme", "codepoint"] = Field(description="what a character error counts")
    words: Words | None = Field(None, description="the word metrics' tokenizer and the version of their rules; absent "
                                                  "(records from before 0.11): whitespace, version 1")
    elements: EvidenceElements | None = Field(None, description="how elements were matched, when the element "
                                                               "metrics were scored")
    scorer: str = Field(description="the linecaster that scored (linecaster.evaluation.scorer())")


class EvidenceElements(_Doc):
    """How the element metrics matched elements (``linecaster.evaluation.matching``)."""

    version: int = Field(description="the version of the element scorer's rules (linecaster.evaluation.ELEMENTS_VERSION)")
    lane: Named = Field(description="the lane elements were matched by")


class EvidenceStratum(_Doc):
    """The rates of a run on one stratum (``linecaster.evaluation.strata``): elements or pages with one value."""

    pages: int = Field(description="the pages with elements in it (page strata: its pages)")
    elements: int = Field(0, description="the ground truth's and output's elements in it (page strata: 0)")
    metrics: dict[str, Metric]

    model_config = ConfigDict(extra="forbid")


class EvidenceSlice(_Doc):
    """The rates of a run on one slice of a benchmark's pages (``linecaster.evaluation.slices``)."""

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
                                             "those with tables, formulas, neither (linecaster.evaluation.slices)")
    strata: dict[str, dict[str, EvidenceStratum]] = Field(default_factory=dict, description="the rates by stratum: "
                                                          "dimension (pages:<dimension> for page rates) -> value -> "
                                                          "rates (linecaster.evaluation.strata)")
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
        """Scored the same way: the same benchmark (hash), policy, output strategy, lanes (by hash), unit, word
        metrics (tokenizer and rules) and element metrics (rules and matching lane); a record with a hash missing
        (upgraded from evidence/2) is comparable to none."""
        def key(e):
            sc = e.scoring
            named = [sc.policy, sc.output, *sc.lanes] if sc else []
            if e.benchmark is None or sc is None or any(n.sha256 is None for n in named):
                return None
            words = sc.words or Words()
            el = (sc.elements.version, sc.elements.lane.id, sc.elements.lane.sha256) if sc.elements else None
            return (e.benchmark.sha256, *((n.id, n.sha256) for n in named), sc.unit, words.tokenizer, words.version,
                    el)
        a, b = key(self), key(other)
        return a is not None and a == b


def upgrade_evidence_2(data: dict) -> dict:
    """An ``evidence/2`` record as ``evidence/3``: lanes by their strategy (``linecaster.evaluation.lanes.LEGACY``),
    the unit ``codepoint``, the output ``literal``, no hashes (it is comparable to no record written since)."""
    from linecaster.evaluation.lanes import LEGACY

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


