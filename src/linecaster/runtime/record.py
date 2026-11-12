"""The run record's format (``OUT/run.yaml``, schema ``linecaster.run-record/1``) as pydantic models: the source of
its JSON Schema (``catalog/schemas/run-record-1.json``, ``linecaster catalog schemas``) and the check
``provenance.run_record`` runs before a record is written. Import-light: pydantic only."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Script(_Record):
    path: str = Field(description="the pipeline script, relative to its git checkout (else its file name)")
    sha256: str | None = Field(None, description="the script file's hash (sha256:<hex>)")


class Recipe(_Record):
    ref: str = Field(description="the recipe edition, id@edition")
    pipeline: str = Field(description="the pipeline id it fills")
    sha256: str = Field(description="the edition's hash")
    released: bool
    overrides: dict[str, Any] | None = Field(None, description="what the command line gave instead of the recipe")


class Contract(_Record):
    role: str
    unit: str
    unit_out: str | None = None
    reads: list[str] | None = None
    adds: list[str] | None = None
    replaces: list[str] | None = None
    removes: list[str] | None = None


class BlockEntry(_Record):
    id: str = Field(description="the block's node in the plan's graph")
    block: str = Field(description="its class name")
    name: str | None = Field(None, description="its datatrove name, where it differs from the class name")
    class_: str = Field(alias="class", description="module:Class")
    params: dict[str, Any] | None = Field(None, description="its constructor's parameters as built (to_dict())")
    contract: Contract
    shape: str | None = Field(None, description="unit (a per-unit transform) or stream")
    composite: str | None = Field(None, description="the composites it sits in, outermost first, joined by /")
    group: str | None = None
    when: str | None = Field(None, description="its condition")
    provides: str | None = None


class Stage(_Record):
    name: str
    tasks: int
    blocks: list[BlockEntry]


class Software(_Record):
    linecaster: str
    commit: str | None = None
    dirty: bool | None = None
    python: str
    packages: dict[str, str] = Field(default_factory=dict)


class SampleListing(_Record):
    scope: Literal["pages", "items"] = Field(description="what the listing's hash covers: its (item, page) ids, or "
                                                         "its item ids (manifests: pages are known once read)")
    items: int
    pages: int | None = None
    duplicates: int = Field(0, description="ids listed more than once (their first entry is read)")
    manifests_read: int | None = Field(None, description="manifests read to compute the sample")
    sha256: str = Field(description="sha256 of the distinct sorted lines item_id<TAB>page_id (or item_id), each "
                                    "with a newline")


class SampleSelected(_Record):
    items: int
    pages: int
    sha256: str = Field(description="sha256 of the sample's lines item_id<TAB>page_id, each with a newline, in order")


class SampleRecord(_Record):
    rule: str = Field(description="the rule's id (linecaster.sample/1, linecaster.data.sample)")
    hash: str = Field(description="the hashes that rank items and pages")
    pages: int | None = Field(None, description="N: at most this many pages in all")
    items: int | None = Field(None, description="M: at most this many items")
    per_item: int | None = Field(None, description="K: at most this many pages of each item")
    seed: int
    listing: SampleListing
    selected: SampleSelected
    file: str = Field(description="the sample's file in the run folder")


class RunRecord(_Record):
    schema_: Literal["linecaster.run-record/1"] = Field("linecaster.run-record/1", alias="schema")
    created: str = Field(description="when the run was launched, UTC (YYYY-MM-DDTHH:MM:SSZ)")
    script: Script | None = None
    recipe: Recipe | None = None
    argv: list[str] | None = Field(None, description="the command line, --env values redacted")
    on: str | None = None
    executor: str | None = None
    tasks: int | None = None
    workers: int | None = None
    options: dict[str, Any] = Field(default_factory=dict, description="the other parsed options")
    pipeline: list[Stage] = Field(default_factory=list, description="the stages with their blocks, in order")
    pipeline_sha256: str = Field(description="the hash of the pipeline's functional parameters: a resume into the "
                                             "same run folder needs the same one")
    image: str | None = Field(None, description="HF Jobs: the container image")
    dependencies: list[str] | None = Field(None, description="HF Jobs: what each Job installs")
    constraints: list[str] | None = Field(None, description="HF Jobs: the versions each Job resolves, from the "
                                                            "script's lock (name==version)")
    overrides: list[str] | None = Field(None, description="HF Jobs: the script's override-dependencies")
    sample: SampleRecord | None = Field(None, description="the sample the run read (--sample ...): the rule, its "
                                                          "seed and limits, the listing and the sample's hashes")
    software: Software
