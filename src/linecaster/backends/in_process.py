"""``InProcess``: the engine runs in the pipeline's process (loaded lazily in the worker, never pickled), and
``resolve`` for ``module:Class`` specs."""
from __future__ import annotations

import importlib
from typing import Protocol

from ..data.transcription import Transcription


class EngineModel(Protocol):
    step: str
    name: str

    def load(self) -> None: ...

    def __call__(self, image, transcription: Transcription, **params) -> Transcription: ...


def resolve(spec: str):
    """``"package.module:Attribute"`` -> the attribute."""
    module, _, attr = spec.partition(":")
    return getattr(importlib.import_module(module), attr)


class InProcess:
    """The engine runs in the pipeline's process. ``spec`` names its class; ``kwargs`` construct it. Nothing is
    imported until ``warm_up()`` (or the first ``model()``): a pipeline builds, checks and describes without the
    engine installed."""

    served = False

    def __init__(self, spec: str, **kwargs):
        self.spec, self.kwargs = spec, kwargs
        self.preset: str | None = None           # id@edition when built from a catalog preset
        self.preset_sha256: str | None = None
        self.overrides: dict | None = None       # options given over the preset's (the pipelines' --set)
        self._model = None

    @classmethod
    def from_preset(cls, ref: str) -> "InProcess":
        """The engine and options of catalog preset ``ref`` (``id`` or ``id@edition``)."""
        from ..catalog.registry import engine_spec

        spec, kwargs, resolved = engine_spec(ref)
        backend = cls(spec, **kwargs)
        backend.preset, backend.preset_sha256 = resolved.ref, resolved.sha256
        return backend

    def warm_up(self) -> None:
        """Import, construct and load the engine (idempotent)."""
        self.model()

    def model(self) -> EngineModel:
        if self._model is None:
            self._model = resolve(self.spec)(**self.kwargs)
            self._model.load()
        return self._model

    def describe(self) -> str:
        return "in-process"

    def __getstate__(self):   # never pickle a loaded model (datatrove pickles the pipeline)
        return {"spec": self.spec, "kwargs": self.kwargs, "preset": self.preset, "preset_sha256": self.preset_sha256,
                "overrides": self.overrides, "_model": None}


