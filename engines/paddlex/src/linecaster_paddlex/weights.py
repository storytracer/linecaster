"""PaddleX's official models at pinned revisions.

PaddleX itself downloads an official model from Hugging Face as ``PaddlePaddle/<name>_onnx`` (the ONNX Runtime
engine) or ``PaddlePaddle/<name>_safetensors`` (the transformers engine), always the repository's current
``main``, into ``~/.paddlex/official_models/`` (``paddlex.inference.utils.official_models``). Here the same
repositories are pinned in the catalog (``linecaster/catalog/data/models/<name>-onnx/model.yaml``, the name
lowercased with ``_`` as ``-``): a preset passes its pin as ``weights``, a model name resolves to its model
document's newest pin, and the snapshot at that commit (Hugging Face cache, checked against the pinned
sha256) goes to ``create_predictor(model_dir=...)``. A name the catalog does not know is left to PaddleX's
own download.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: the package PaddleX downloads for each engine
PACKAGES = {"onnxruntime": "onnx", "transformers": "safetensors"}


def model_id(name: str, package: str = "onnx") -> str:
    """The catalog id of PaddleX model ``name``'s ``package`` (``PP-OCRv6_medium_det`` -> ``pp-ocrv6-medium-det-onnx``)."""
    return f"{name}_{package}".lower().replace("_", "-")


def catalog_weights(name: str, package: str = "onnx", revision: str | None = None) -> dict | None:
    """``weights`` for PaddleX model ``name`` from its model document: the pin with ``revision``, else the newest
    pin; ``None`` when the catalog has no document for it."""
    from linecaster.catalog.fetch import weights_of
    from linecaster.catalog.registry import catalog

    mid = model_id(name, package)
    if mid not in catalog().models:
        if revision is not None:
            raise KeyError(f"{name}: revision {revision} requested, but the catalog has no model {mid!r}")
        return None
    return weights_of(mid, revision)


def model_dir(weights: dict) -> str:
    """The snapshot of a pin (``weights``: model, source, revision, files) in the Hugging Face cache, downloaded
    on first use, every pinned file checked against its sha256."""
    from linecaster.catalog.fetch import hf_snapshot

    return str(hf_snapshot(weights))


def check(name: str, weights: dict | None, engine: str = "onnxruntime") -> None:
    """``weights`` must be the pin of PaddleX model ``name``'s package for ``engine``."""
    if weights is not None and weights["model"] != model_id(name, PACKAGES[engine]):
        raise ValueError(f"model_name={name!r} does not name the pinned weights {weights['model']!r} "
                         f"(expected {model_id(name, PACKAGES[engine])!r})")


def resolve(name: str, weights: dict | None = None, engine: str = "onnxruntime") -> tuple[str | None, str | None]:
    """``(model folder, revision)`` for PaddleX model ``name``: the pin ``weights``, else the catalog's newest
    pin for the name; ``(None, None)`` (PaddleX downloads it itself) when the catalog does not know the name."""
    check(name, weights, engine)
    if weights is None:
        weights = catalog_weights(name, PACKAGES[engine])
    return (model_dir(weights), weights["revision"]) if weights is not None else (None, None)
