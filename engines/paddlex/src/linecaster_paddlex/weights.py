"""PaddleX's official models at pinned revisions.

PaddleX itself downloads an official model from Hugging Face as ``PaddlePaddle/<name>_onnx`` (the ONNX Runtime
engine) or ``PaddlePaddle/<name>_safetensors`` (the transformers engine), always the repository's current
``main``, into ``~/.paddlex/official_models/`` (``paddlex.inference.utils.official_models``). Here the same
repositories are pinned in the catalogue (``linecaster_paddlex/catalog/models/<name>-onnx/model.md``, the name
lowercased with ``_`` as ``-``): a preset passes its pin as ``weights``, a model name resolves to its model
document's newest pin, and the snapshot at that commit (Hugging Face cache, checked against the pinned
sha256) goes to ``create_predictor(model_dir=...)``. A name the catalogue does not know is left to PaddleX's
own download.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: the package PaddleX downloads for each engine
PACKAGES = {"onnxruntime": "onnx", "transformers": "safetensors"}


def model_id(name: str, package: str = "onnx") -> str:
    """The catalogue id of PaddleX model ``name``'s ``package`` (``PP-OCRv6_medium_det`` -> ``pp-ocrv6-medium-det-onnx``)."""
    return f"{name}_{package}".lower().replace("_", "-")


def catalogue_weights(name: str, package: str = "onnx", revision: str | None = None) -> dict | None:
    """``weights`` for PaddleX model ``name`` from its model document: the pin with ``revision``, else the newest
    pin; ``None`` when the catalogue has no document for it."""
    from linecaster.catalog.registry import catalog

    c = catalog()
    mid = model_id(name, package)
    if mid not in c.models:
        if revision is not None:
            raise KeyError(f"{name}: revision {revision} requested, but the catalogue has no model {mid!r}")
        return None
    m = c.model(mid)
    pin = m.pin(revision) if revision is not None else m.pins[-1]
    return {"model": m.id, "source": m.source.model_dump(), "revision": pin.revision, "files": dict(pin.files)}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def model_dir(weights: dict) -> str:
    """The snapshot of a pin (``weights``: model, source, revision, files) in the Hugging Face cache, downloaded
    on first use, every pinned file checked against its sha256."""
    from huggingface_hub import snapshot_download

    source = weights["source"]
    if source.get("kind") != "hf":
        raise ValueError(f"PaddleX weights come from Hugging Face; {weights['model']} is {source}")
    revision = weights["revision"]
    logger.info(f"PaddleX model {weights['model']}: {source['ref']}@{revision[:12]} (Hugging Face cache or download)")
    root = Path(snapshot_download(source["ref"], revision=revision))
    for name, sha in weights["files"].items():
        path, expected = root / name, sha.split(":", 1)[1]
        # the Hugging Face cache names an LFS blob by its sha256; anything else is hashed
        if not path.exists() or (path.resolve().name != expected and _sha256(path) != expected):
            raise ValueError(f"{path}: missing or its sha256 differs from the pin of {weights['model']}@{revision[:12]}")
    return str(root)


def check(name: str, weights: dict | None, engine: str = "onnxruntime") -> None:
    """``weights`` must be the pin of PaddleX model ``name``'s package for ``engine``."""
    if weights is not None and weights["model"] != model_id(name, PACKAGES[engine]):
        raise ValueError(f"model_name={name!r} does not name the pinned weights {weights['model']!r} "
                         f"(expected {model_id(name, PACKAGES[engine])!r})")


def resolve(name: str, weights: dict | None = None, engine: str = "onnxruntime") -> tuple[str | None, str | None]:
    """``(model folder, revision)`` for PaddleX model ``name``: the pin ``weights``, else the catalogue's newest
    pin for the name; ``(None, None)`` (PaddleX downloads it itself) when the catalogue does not know the name."""
    check(name, weights, engine)
    if weights is None:
        weights = catalogue_weights(name, PACKAGES[engine])
    return (model_dir(weights), weights["revision"]) if weights is not None else (None, None)
