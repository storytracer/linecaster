"""Fetching a model pin's files, each checked against its pinned sha256 (one place for every engine).

``weights`` is what ``registry.engine_spec`` passes an engine: ``{"model", "source", "revision", "files"}``.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from ..errors import CatalogError
from .registry import catalog, sha256_file


def weights_of(model_id: str, revision: str | None = None) -> dict:
    """``weights`` for the pin ``revision`` of model ``model_id`` (the newest pin when ``None``)."""
    m = catalog().model(model_id)
    pin = m.pin(revision) if revision is not None else m.pins[-1]
    return {"model": m.id, "source": m.source.model_dump(), "revision": pin.revision, "files": dict(pin.files)}


def check(path: str | Path, sha: str, label: str) -> Path:
    """``path`` if its content is ``sha`` (``sha256:<hex>``); the Hugging Face cache names an LFS blob by its
    sha256, so a cached file is checked by name before it is hashed."""
    path = Path(path)
    expected = sha.split(":", 1)[1]
    if not path.exists() or (path.resolve().name != expected and sha256_file(path) != sha):
        raise CatalogError(f"{path}: missing, or its sha256 differs from the pin of {label}")
    return path


def _hf(weights: dict) -> tuple[str, str, str]:
    source = weights["source"]
    if source.get("kind") != "hf":
        raise CatalogError(f"{weights['model']}: not on Hugging Face ({source})")
    return source["ref"], weights["revision"], f"{weights['model']}@{weights['revision'][:12]}"


def hf_file(weights: dict, name: str, download: bool = True) -> Path:
    """One pinned file of a Hugging Face pin, from the cache or downloaded, checked."""
    from huggingface_hub import hf_hub_download

    repo, revision, label = _hf(weights)
    logger.info("{label}: {repo} {name} (Hugging Face cache or download)", label=label, repo=repo, name=name)
    path = hf_hub_download(repo, name, revision=revision, local_files_only=not download)
    return check(path, weights["files"][name], label)


def hf_snapshot(weights: dict, download: bool = True) -> Path:
    """The whole Hugging Face pin as a folder, every pinned file checked."""
    from huggingface_hub import snapshot_download

    repo, revision, label = _hf(weights)
    logger.info("{label}: {repo} (Hugging Face cache or download)", label=label, repo=repo)
    root = Path(snapshot_download(repo, revision=revision, local_files_only=not download))
    for name, sha in weights["files"].items():
        check(root / name, sha, label)
    return root
