"""Tesseract's language data (``.traineddata``) from the tesseract-ocr repositories, pinned to a commit.

``best`` is tessdata_best (the most accurate LSTM models, float), ``fast`` tessdata_fast (integer,
faster). A language is a code such as ``eng``, ``deu``, ``lat`` or ``frk`` or a script such as
``script/Latin``; ``+`` combines several (``eng+lat``). The commits and the sha256 of the pinned files live in
the catalogue (``linecaster/catalog/data/models/tessdata-{best,fast}/model.yaml``): ``data`` resolves to its
model document's newest pin, a preset passes its pin as ``weights``. Files land in
``~/.cache/linecaster/tessdata`` (``LINECASTER_CACHE``) under the repository and commit, and every pinned file
is checked against its sha256 whenever it is used; with ``weights`` only pinned files are accepted.
"""
from __future__ import annotations

import hashlib
import logging
import os
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: the catalogue's model document for each kind of tessdata
MODEL_IDS = {"best": "tessdata-best", "fast": "tessdata-fast"}


@dataclass(frozen=True)
class Tessdata:
    repo: str                                   # owner/name on GitHub
    commit: str
    files: dict[str, str] = field(default_factory=dict)   # path in the repository -> sha256:<hex>
    model: str | None = None                    # the catalogue model id

    @classmethod
    def of(cls, weights: dict) -> "Tessdata":
        """From a pin (``weights``: model, source, revision, files) as ``engine_spec`` passes it."""
        source = weights["source"]
        prefix = "https://github.com/"
        if source.get("kind") != "git" or not source["ref"].startswith(prefix):
            raise ValueError(f"tessdata comes from a GitHub repository; {weights['model']} is {source}")
        return cls(source["ref"][len(prefix):].rstrip("/"), weights["revision"], dict(weights["files"]),
                   weights["model"])


def tessdata(data: str = "best") -> Tessdata:
    """The newest pin of ``data``'s model document (``best``, ``fast``)."""
    from linecaster.catalog.registry import catalog

    m = catalog().model(MODEL_IDS[data])
    pin = m.pins[-1]
    return Tessdata.of({"model": m.id, "source": m.source.model_dump(), "revision": pin.revision,
                        "files": dict(pin.files)})


def __getattr__(name):   # TESSDATA: kind -> Tessdata, read from the catalogue when asked for
    if name == "TESSDATA":
        return {data: tessdata(data) for data in MODEL_IDS}
    raise AttributeError(name)


def cache_root() -> Path:
    return Path(os.environ.get("LINECASTER_CACHE", Path.home() / ".cache" / "linecaster")) / "tessdata"


def _fetch(td: Tessdata, name: str) -> bytes:
    url = f"https://raw.githubusercontent.com/{td.repo}/{td.commit}/{name}"
    with urllib.request.urlopen(url, timeout=300) as r:
        data = r.read()
    # a git symlink comes back as its target's name (frk.traineddata -> another file)
    if len(data) < 256 and data.strip().endswith(b".traineddata"):
        target = (Path(name).parent / data.strip().decode()).as_posix()
        return _fetch(td, target)
    return data


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tessdata_dir(lang: str, data: str = "best", download: bool = True, td: Tessdata | None = None,
                 strict: bool = False) -> Path:
    """The tessdata folder holding every language of ``lang`` (``+``-separated), downloaded on first use.
    ``td``: the pin (else ``data``'s newest pin). A pinned file is checked against its sha256 (a cached copy that
    differs is fetched again); with ``strict`` every language must be a pinned file."""
    td = td or tessdata(data)
    root = cache_root() / f"{td.repo.split('/')[-1]}-{td.commit[:12]}"
    for code in lang.split("+"):
        name = f"{code}.traineddata"
        expected = td.files.get(name)
        if expected is None and strict:
            raise ValueError(f"{name} is not pinned in {td.model or td.repo}@{td.commit[:12]} "
                             f"(pinned: {sorted(td.files)})")
        expected = expected.split(":", 1)[1] if expected else None
        path = root / name
        if path.exists() and (expected is None or sha256(path) == expected):
            continue
        if not download:
            raise FileNotFoundError(path)
        logger.info(f"tesseract {code}: {td.repo}@{td.commit[:12]} (download)")
        blob = _fetch(td, name)
        if expected is not None and hashlib.sha256(blob).hexdigest() != expected:
            raise ValueError(f"{name} from {td.repo}@{td.commit[:12]}: sha256 differs from the pin")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(blob)
        tmp.rename(path)
    return root
