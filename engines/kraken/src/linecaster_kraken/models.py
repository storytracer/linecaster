"""kraken's model files, from their pinned Hugging Face mirrors (``huggingface_hub``).

kraken's models always come from the Hugging Face mirrors of their Zenodo releases
(``small-models-for-glam``): Zenodo throttles downloads badly. The mirrors are byte-identical to the
Zenodo records (the DOIs are provenance, in the model documents). The PP-OCRv6 recognisers' revisions and
file hashes live in the catalogue (``linecaster/catalog/data/models/kraken-ppocrv6-<size>/model.yaml``): a
size name resolves to its model document's newest pin, a preset passes its pin as ``weights``. Files land in
the Hugging Face cache (``~/.cache/huggingface/hub``, ``HF_HOME``; ``HF_HUB_OFFLINE=1`` reads it without the
network) and are checked against the pinned sha256.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

SIZES = ("tiny", "small", "medium")
DEFAULT_SIZE = "medium"
#: the catalogue's model document of each PP-OCRv6 size
MODEL_IDS = {size: f"kraken-ppocrv6-{size}" for size in SIZES}


@dataclass(frozen=True)
class KrakenModel:
    """One kraken model file on a Hugging Face mirror of its Zenodo release."""

    repo: str
    filename: str
    revision: str   # the mirror's commit, so a run always gets the same file
    doi: str        # the Zenodo release the mirror copies: provenance and citation


#: kraken's blla segmenter: the BLLA base model (Sept 2026), newer than the one kraken 7.1.1 bundles (our fork
#: bundles this file too). Not used by an engine here, so not in the catalogue; the recognisers are.
KRAKEN_MODELS = {
    "blla": KrakenModel("small-models-for-glam/kraken-blla-base", "blla.mlmodel",
                        "3e91a744c37defc10c3714d9f0f4fa54174fe5c0", "10.5281/zenodo.22879549"),
}

Log = Callable[[str], None]


def size_weights(size: str) -> dict:
    """``weights`` (as ``linecaster.catalog.registry.engine_spec`` passes them) for a PP-OCRv6 size: the newest
    pin of its model document in the catalogue."""
    from linecaster.catalog.fetch import weights_of

    return weights_of(MODEL_IDS[size])


def fetch_weights(weights: dict, log: Log = logger.info, download: bool = True) -> Path:
    """The model file of a pin (``weights``: model, source, revision, files), from the Hugging Face cache or
    downloaded, checked against its pinned sha256."""
    from linecaster.catalog.fetch import hf_file

    files = [k for k in weights["files"] if k.endswith((".safetensors", ".mlmodel"))]
    if len(files) != 1:
        raise ValueError(f"{weights['model']}: expected one kraken model file in the pin, got {sorted(files)}")
    log(f"kraken model {weights['model']}@{weights['revision'][:12]}")
    return hf_file(weights, files[0], download)


def kraken_model_file(name: str, log: Log = logger.info, download: bool = True) -> Path:
    """The file of kraken model ``name`` (a PP-OCRv6 size, through the catalogue, or a key of ``KRAKEN_MODELS``)
    from its pinned Hugging Face mirror: downloaded on first use, served from the Hugging Face cache afterwards.
    ``download=False`` only looks in the cache and raises when the file is not there."""
    if name in SIZES:
        return fetch_weights(size_weights(name), log, download)
    from huggingface_hub import hf_hub_download

    m = KRAKEN_MODELS[name]
    log(f"kraken model {name}: {m.repo}@{m.revision[:12]} (Hugging Face cache or download)")
    return Path(hf_hub_download(m.repo, m.filename, revision=m.revision, local_files_only=not download))


def resolve_kraken_model(spec: str | Path = DEFAULT_SIZE, log: Log = logger.info, download: bool = True) -> Path:
    """The recognition model for ``spec``: a size name (from Hugging Face) or a path to a kraken model file."""
    p = Path(spec)
    if p.is_file():
        return p
    size = str(spec).lower()
    if size not in SIZES:
        raise FileNotFoundError(f"{spec} is neither a model size ({', '.join(SIZES)}) nor a kraken model file.")
    return kraken_model_file(size, log, download)
