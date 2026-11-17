"""Every format linecaster writes, by schema id, with its pydantic model: the catalog's kinds and the data formats
(page records, documents, run records, benchmarks, evidence records). The JSON Schemas in ``catalog/schemas/`` are
generated from them (``linecaster catalog schemas``), and a test fails when a committed one differs."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from linecaster.catalog.schema import (SCHEMA_DIR, ModelDoc, NormalizationDoc, PolicyDoc, PresetDoc, RecipeDoc, StrategyDoc,
                                       schema_file)
from linecaster.catalog.vocabulary import VocabularyDoc
from linecaster.conventions.model import ConventionsDoc
from linecaster.data.page import PAGE_SCHEMA, Page
from linecaster.document.model import SCHEMA as DOCUMENT_SCHEMA, Document
from linecaster.evaluation.benchmark import Benchmark
from linecaster.evaluation.evidence_format import Evidence, Evidence2, Evidence3
from linecaster.execution.record import RunRecord

#: every format, by schema id
FORMATS: dict[str, type[BaseModel]] = {
    "linecaster.model": ModelDoc,
    "linecaster.preset": PresetDoc,
    "linecaster.recipe": RecipeDoc,
    "linecaster.policy": PolicyDoc,
    "linecaster.conventions": ConventionsDoc,
    "linecaster.normalization": NormalizationDoc,
    "linecaster.strategy": StrategyDoc,
    "linecaster.vocabulary": VocabularyDoc,
    "linecaster.evidence/1": Evidence,
    "linecaster.evidence/2": Evidence2,
    "linecaster.evidence/3": Evidence3,
    "linecaster.benchmark/2": Benchmark,
    "linecaster.run-record/2": RunRecord,
    PAGE_SCHEMA: Page,                   # a page record's `page` (the row: schema, id, text, page, errors)
    DOCUMENT_SCHEMA: Document,
}


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
