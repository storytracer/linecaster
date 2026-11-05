"""``linecaster catalog pin``: write a model document from its source, with the upstream card copied verbatim.

* Hugging Face: the revision (a commit; a tag or branch is resolved and kept as ``tag``), the sha256 of every
  LFS file, ``README.md`` and any license file at that commit, copied unchanged into
  ``models/<id>/upstream/<revision>/``.
* git (GitHub): a commit, the named files (downloaded and hashed) and the repository README at that commit.

An existing ``model.yaml`` keeps its fields and comments, and ``model.md`` its prose; the new pin is added (a known
revision is left as it is). License and languages are taken from the card's front matter for a new model.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import shutil
import tempfile
import urllib.request
from pathlib import Path

from . import yamlio
from .registry import sha256_file, write_entry
from .schema import ModelDoc, Pin

#: card license ids (Hugging Face uses lowercase SPDX-like ids) -> SPDX
SPDX = {"apache-2.0": "Apache-2.0", "mit": "MIT", "bsd-3-clause": "BSD-3-Clause", "cc-by-4.0": "CC-BY-4.0",
        "cc-by-sa-4.0": "CC-BY-SA-4.0", "cc-by-nc-4.0": "CC-BY-NC-4.0", "cc-by-nc-sa-4.0": "CC-BY-NC-SA-4.0",
        "gpl-3.0": "GPL-3.0-only", "agpl-3.0": "AGPL-3.0-only", "lgpl-3.0": "LGPL-3.0-only",
        "openrail": "OpenRAIL", "llama3": "Llama-3", "gemma": "Gemma"}
#: ISO 639-1 -> ISO 639-3 for the languages model cards name most
ISO639_3 = {"en": "eng", "de": "deu", "fr": "fra", "es": "spa", "it": "ita", "nl": "nld", "pt": "por",
            "sv": "swe", "da": "dan", "no": "nor", "nb": "nob", "fi": "fin", "pl": "pol", "cs": "ces",
            "ru": "rus", "uk": "ukr", "el": "ell", "la": "lat", "zh": "zho", "ja": "jpn", "ko": "kor",
            "ar": "ara", "he": "heb", "fa": "fas", "hi": "hin", "ta": "tam", "te": "tel", "th": "tha",
            "tr": "tur", "hu": "hun", "ro": "ron", "bg": "bul", "hr": "hrv", "sr": "srp", "sk": "slk",
            "sl": "slv", "et": "est", "lv": "lav", "lt": "lit", "vi": "vie", "id": "ind", "ms": "msa",
            "multilingual": "mul"}
LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "MODEL_LICENSE", "MODEL_LICENSE.md", "LICENCE")


def folder(revision: str) -> str:
    return revision.replace("/", "_")


def _card_meta(card: Path) -> dict:
    try:
        return yamlio.read_front_matter(card)[0]
    except ValueError:
        return {}


def _languages(meta: dict) -> list[str]:
    raw = meta.get("language") or []
    raw = [raw] if isinstance(raw, str) else raw
    return [ISO639_3.get(str(x).lower(), str(x).lower()) for x in raw]


def _write(directory: Path, model_id: str, source: dict, pin: Pin, card: Path, defaults: dict) -> Path:
    path = directory / "models" / model_id / "model.yaml"
    entry = pin.model_dump(mode="python", exclude_none=True)
    if path.exists():
        doc = yamlio.read_rt(path)
        if not any(p["revision"] == pin.revision for p in doc["pins"]):
            doc["pins"].append(yamlio.blocks(entry))
        ModelDoc.model_validate(yamlio.load(yamlio.dump_rt(doc)))
        path.write_text(yamlio.dump_rt(doc), encoding="utf-8")
        return path
    cmeta = _card_meta(card)
    lic = str(cmeta.get("license", "")).lower()
    meta = {"schema": "linecaster.model/1", "id": model_id, "version": None, "source": source, "pins": [entry],
            "license": SPDX.get(lic, cmeta.get("license_name") or lic or "unknown"),
            "languages": _languages(cmeta), "scripts": [], "derived_from": []}
    meta.update({k: v for k, v in defaults.items() if v is not None})
    ModelDoc.model_validate(meta)
    return write_entry(path, meta, f"{model_id}: the upstream card is in `{pin.card}`.")


def pin_hf(directory: str | Path, model_id: str, repo: str, revision: str | None = None,
           today: dt.date | None = None, **defaults) -> Path:
    from huggingface_hub import HfApi, hf_hub_download

    directory = Path(directory)
    info = HfApi().model_info(repo, revision=revision or "main", files_metadata=True)
    sha = info.sha
    tag = (revision or "main") if (revision or "main") != sha else None
    files = {s.rfilename: f"sha256:{s.lfs.sha256}" for s in info.siblings if getattr(s, "lfs", None)}
    up = directory / "models" / model_id / "upstream" / folder(sha)
    up.mkdir(parents=True, exist_ok=True)
    names = {s.rfilename for s in info.siblings}
    card = up / "README.md"
    if "README.md" in names:
        shutil.copyfile(hf_hub_download(repo, "README.md", revision=sha), card)
    else:
        card.write_text("", encoding="utf-8")   # the repository has no card; recorded as empty
    license_file = None
    for name in LICENSE_NAMES:
        if name in names:
            shutil.copyfile(hf_hub_download(repo, name, revision=sha), up / name)
            license_file = f"upstream/{folder(sha)}/{name}"
            break
    pin = Pin(revision=sha, tag=tag, pinned=today or dt.date.today(), files=dict(sorted(files.items())),
              card=f"upstream/{folder(sha)}/README.md", card_sha256=sha256_file(card), license_file=license_file)
    return _write(directory, model_id, {"kind": "hf", "ref": repo}, pin, card, defaults)


def _download(url: str, dest: Path) -> str:
    h = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=600) as r, open(dest, "wb") as f:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            h.update(chunk)
            f.write(chunk)
    return f"sha256:{h.hexdigest()}"


def pin_github(directory: str | Path, model_id: str, repo: str, commit: str, files: list[str],
               tag: str | None = None, today: dt.date | None = None, **defaults) -> Path:
    """``repo`` is ``owner/name`` on GitHub; ``commit`` a full sha; ``files`` paths in the repository."""
    directory = Path(directory)
    raw = f"https://raw.githubusercontent.com/{repo}/{commit}"
    up = directory / "models" / model_id / "upstream" / folder(commit)
    up.mkdir(parents=True, exist_ok=True)
    card = up / "README.md"
    _download(f"{raw}/README.md", card)
    hashes = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name in files:
            hashes[name] = _download(f"{raw}/{name}", Path(tmp) / "f")
    license_file = None
    for name in LICENSE_NAMES:
        try:
            _download(f"{raw}/{name}", up / name)
            license_file = f"upstream/{folder(commit)}/{name}"
            break
        except Exception:  # noqa: BLE001 - not every repository has one under each name
            (up / name).unlink(missing_ok=True)
    pin = Pin(revision=commit, tag=tag, pinned=today or dt.date.today(), files=dict(sorted(hashes.items())),
              card=f"upstream/{folder(commit)}/README.md", card_sha256=sha256_file(card), license_file=license_file)
    return _write(directory, model_id, {"kind": "git", "ref": f"https://github.com/{repo}"}, pin, card, defaults)
