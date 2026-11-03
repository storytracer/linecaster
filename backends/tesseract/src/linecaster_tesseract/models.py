"""Tesseract's language data (``.traineddata``) from the tesseract-ocr repositories, pinned to a commit.

``best`` is tessdata_best (the most accurate LSTM models, float), ``fast`` tessdata_fast (integer,
faster). A language is a code such as ``eng``, ``deu``, ``lat`` or ``frk`` or a script such as
``script/Latin``; ``+`` combines several (``eng+lat``). Files land in ``~/.cache/linecaster/tessdata``
(``LINECASTER_CACHE``) under the repository and commit, so every run reads the same files.
"""
from __future__ import annotations

import hashlib
import logging
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tessdata:
    repo: str
    commit: str


TESSDATA = {
    "best": Tessdata("tesseract-ocr/tessdata_best", "e12c65a915945e4c28e237a9b52bc4a8f39a0cec"),
    "fast": Tessdata("tesseract-ocr/tessdata_fast", "87416418657359cb625c412a48b6e1d6d41c29bd"),
}


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


def tessdata_dir(lang: str, data: str = "best", download: bool = True) -> Path:
    """The tessdata folder holding every language of ``lang`` (``+``-separated), downloaded on first use."""
    td = TESSDATA[data]
    root = cache_root() / f"{td.repo.split('/')[-1]}-{td.commit[:12]}"
    for code in lang.split("+"):
        path = root / f"{code}.traineddata"
        if path.exists():
            continue
        if not download:
            raise FileNotFoundError(path)
        logger.info(f"tesseract {code}: {td.repo}@{td.commit[:12]} (download)")
        blob = _fetch(td, f"{code}.traineddata")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(blob)
        tmp.rename(path)
    return root


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
