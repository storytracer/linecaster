"""The catalog of models, presets and evidence (``docs/reference/catalog.md``)."""
from linecaster.catalog.registry import Catalog, Resolved, catalog, engine_class, engine_ids, engine_spec
from linecaster.catalog.schema import OCRD_STEPS, PRODUCES, STEPS, ModelDoc, PresetDoc

__all__ = ["Catalog", "ModelDoc", "OCRD_STEPS", "PRODUCES", "PresetDoc", "Resolved", "STEPS",
           "catalog", "engine_class", "engine_ids", "engine_spec"]
