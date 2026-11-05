"""The catalog of models, presets and evidence (``docs/reference/catalog.md``)."""
from .registry import Catalog, Resolved, catalog, engine_class, engine_ids, engine_spec
from .schema import OCRD_STEPS, PRODUCES, STEPS, Evidence, ModelDoc, PresetDoc

__all__ = ["Catalog", "Evidence", "ModelDoc", "OCRD_STEPS", "PRODUCES", "PresetDoc", "Resolved", "STEPS",
           "catalog", "engine_class", "engine_ids", "engine_spec"]
