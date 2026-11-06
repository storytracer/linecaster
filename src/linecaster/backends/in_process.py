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
    """Runs a model block's engine in the pipeline's process.

    Nothing is imported until ``warm_up()`` (or the first ``model()``): a pipeline builds, checks and describes
    without the engine installed. The engine is loaded in the worker and never pickled (a pickled backend carries
    its spec and options only). ``InProcess.from_preset(ref)`` builds one from a catalog preset and records the
    preset edition and its hash, which the block stamps on every step it records.

    Args:
        spec: the engine's class, ``"package.module:Class"``.
        **kwargs: the keyword arguments that construct it (the engine's options; a preset's ``weights`` besides).

    Example:
        from linecaster.backends import InProcess
        from linecaster.blocks.recognition import LineRecognizer

        LineRecognizer(InProcess("linecaster_kraken:KrakenRecognitionEngine", model="medium"))
        LineRecognizer(InProcess.from_preset("kraken-ppocrv6-medium@1"))
    """

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

    def to_dict(self) -> dict:
        """The backend as the run record names it: the engine class, its options (a preset's with ``overrides``
        over them), and the preset edition and its hash when it came from one."""
        out = {"backend": "in-process", "engine": self.spec, "options": self.kwargs}
        for k in ("preset", "preset_sha256", "overrides"):
            if getattr(self, k, None):
                out[k] = getattr(self, k)
        from ..blocks.base.block import plain

        return plain(out)

    def __getstate__(self):   # never pickle a loaded model (datatrove pickles the pipeline)
        return {"spec": self.spec, "kwargs": self.kwargs, "preset": self.preset, "preset_sha256": self.preset_sha256,
                "overrides": self.overrides, "_model": None}


