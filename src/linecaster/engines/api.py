"""The engine API: what an engine package may import from linecaster besides the data model (``linecaster.data``).

An engine package (``linecaster-kraken``, ``linecaster-paddlex``, ``linecaster-tesseract``, a derivative's own)
depends on these names and on ``linecaster.data`` only, so linecaster's internals can change without breaking it
(``tests/test_import_rule.py`` reads the engine packages in ``engines/`` and fails on any other ``linecaster``
import):

* ``Engine``: the protocol of a model engine (``engine_id``, ``step``, ``capabilities``, ``Options``, ``load()``,
  ``__call__(image, transcription, **params) -> Transcription``); ``Capabilities``, the model of ``capabilities``
  (unit and produces), from the catalog's schema;
* the weight helpers: ``weights_of`` (a model pin as the ``weights`` a preset passes), ``hf_file`` and
  ``hf_snapshot`` (a Hugging Face pin's files, checked against their pinned sha256), and ``model_entry`` (a model's
  catalog entry, for lookups).

Import-light, like the data model: the catalog is imported only when a helper is called.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

from ..data.transcription import Transcription

if TYPE_CHECKING:
    from ..catalog.schema import Capabilities, ModelDoc

__all__ = ["Capabilities", "Engine", "hf_file", "hf_snapshot", "model_entry", "weights_of"]


@runtime_checkable
class Engine(Protocol):
    """The protocol of a model engine: a class with a versioned id that implements one catalog step.

    ``engine_id`` is ``<provider>.<step>[.<variant>].v<n>`` (the entry point's name in the group
    ``linecaster.engines``), ``step`` one of the catalog's steps, ``capabilities`` ``{"unit": ..., "produces":
    [...]}`` in the parts vocabulary, ``Options`` a pydantic model of its keyword arguments, each field with a
    description (a preset's ``weights`` besides). ``load()`` loads the weights (exactly the pin it was given);
    ``__call__`` takes the page image as an RGB array (``None`` when the step needs no pixels for the page; the
    image file's bytes, as the reader brought them, for an engine whose optional ``image_input`` is ``"bytes"``: a
    vendor's package that decodes the file itself) and the transcription so far, and returns the transcription with
    its part added and one ``StepInfo`` appended.
    ``linecaster.testing.check_engine`` checks an engine class against it.
    """

    engine_id: ClassVar[str]
    step: ClassVar[str]
    capabilities: ClassVar[dict]

    def load(self) -> None: ...

    def __call__(self, image: Any, transcription: Transcription, **params: Any) -> Transcription: ...


def __getattr__(name: str):
    if name == "Capabilities":          # from the catalog's schema, imported when asked for (import-light)
        from ..catalog.schema import Capabilities

        return Capabilities
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def weights_of(model_id: str, revision: str | None = None) -> dict:
    """Returns the ``weights`` of a model pin, as a preset passes them to its engine.

    ``{"model", "source", "revision", "files"}``: the catalog model's id and source, the pin's revision and its
    files with their sha256.

    Args:
        model_id: the catalog model, e.g. ``kraken-ppocrv6-medium``; unknown is a ``CatalogError``.
        revision: the pin; ``None``: the model's newest pin.
    """
    from ..catalog.fetch import weights_of as fetch

    return fetch(model_id, revision)


def hf_file(weights: dict, name: str, download: bool = True) -> Path:
    """Returns one pinned file of a Hugging Face pin, from the Hugging Face cache or downloaded, checked.

    A file whose sha256 differs from the pin is a ``CatalogError``; so is a pin that is not on Hugging Face.

    Args:
        weights: the pin (``weights_of``, or what a preset passes).
        name: the file's path in the repository, one of the pin's files.
        download: ``False``: only the cache (``HF_HUB_OFFLINE``-like); a missing file raises.
    """
    from ..catalog.fetch import hf_file as fetch

    return fetch(weights, name, download)


def hf_snapshot(weights: dict, download: bool = True) -> Path:
    """Returns a whole Hugging Face pin as a folder, from the cache or downloaded, every pinned file checked.

    Args:
        weights: the pin (``weights_of``, or what a preset passes).
        download: ``False``: only the cache; a missing file raises.
    """
    from ..catalog.fetch import hf_snapshot as fetch

    return fetch(weights, download)


def model_entry(model_id: str) -> "ModelDoc | None":
    """Returns a model's catalog entry (its source, pins, license), or ``None`` when the catalog has none.

    Args:
        model_id: the catalog model's id, e.g. ``pp-ocrv6-medium-det-onnx``.
    """
    from ..catalog.registry import catalog

    entry = catalog().models.get(model_id)
    return entry[1] if entry is not None else None
