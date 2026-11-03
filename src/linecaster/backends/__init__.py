"""Where a block's model runs: in the pipeline's process, or behind a server reached through saturate.

An engine model (in ``engines/<engine>/``, its own package and environment) is a class with a
``step`` (layout, lines, recognition, ...), a ``name``, ``load()`` and ``__call__(image, transcription,
**params) -> Transcription``: it receives the page image (RGB uint8 array) and the transcription so
far, and returns it with its part added. The same class serves both backends:

* ``InProcess("linecaster_paddlex:PaddleLayoutModel", model_name="PP-DocLayoutV3")`` loads it in the
  worker (lazily, so a pickled pipeline carries only the spec);
* ``Served("http://127.0.0.1:8100/v1", model="layout")`` sends each page to ``linecaster serve``,
  which hosts the same class, through saturate.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Protocol

from ..transcription.model import Transcription


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
    """The model runs in the pipeline's process. ``spec`` names its class; ``kwargs`` construct it."""

    served = False

    def __init__(self, spec: str, **kwargs):
        self.spec, self.kwargs = spec, kwargs
        self.preset: str | None = None           # id@edition when built from a catalogue preset
        self.preset_sha256: str | None = None
        self.overrides: dict | None = None       # options given over the preset's (recipes' --set)
        self._model = None

    @classmethod
    def from_preset(cls, ref: str) -> "InProcess":
        """The engine and options of catalogue preset ``ref`` (``id`` or ``id@edition``)."""
        from ..catalog.registry import engine_spec

        spec, kwargs, resolved = engine_spec(ref)
        backend = cls(spec, **kwargs)
        backend.preset, backend.preset_sha256 = resolved.ref, resolved.sha256
        return backend

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


@dataclass
class Served:
    """The model runs behind ``linecaster serve`` (or any server speaking its routes), reached through
    saturate: ``endpoint`` is the server's ``.../v1`` base, ``model`` the name it hosts the model under."""

    endpoint: str
    model: str
    max_window: int = 32
    initial_window: int = 4
    read_timeout: float = 600.0
    served = True

    def describe(self) -> str:
        return f"served {self.endpoint} ({self.model})"
