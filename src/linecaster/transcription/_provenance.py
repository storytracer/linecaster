"""Provenance shared by the serialisers: which software wrote a file, and one record per step.

A step record is the part of a ``ModelInfo`` that identifies what ran: ``step``, ``name``, ``revision``,
``preset``, ``preset_sha256``, ``backend`` and ``settings``. ``measurements`` (seconds, tokens, ...) vary from
run to run and stay in the page rows. Every writer puts the record into its format's own provenance
vocabulary (ALTO ``Processing``, PAGE ``MetadataItem``, hOCR ``meta``) and its reader turns it back into a
``ModelInfo``. lxml-free and import-light on purpose.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from .model import ModelInfo

SOFTWARE = "linecaster"
#: the ``ModelInfo`` fields a page file carries, in this order
RECORD_KEYS = ("step", "name", "revision", "preset", "preset_sha256", "recipe", "recipe_sha256", "backend", "settings")
#: steps that put content into a transcription (the rest modify what is there: unicode, typography, ...)
GENERATING_STEPS = ("layout", "lines", "recognition", "tables", "formulas", "page")

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$")


@lru_cache(maxsize=1)
def version() -> str:
    """linecaster's release (the installed distribution's version, else the package's ``__version__``)."""
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as dist_version

    try:
        return dist_version("linecaster")
    except PackageNotFoundError:
        from .. import __version__

        return __version__


def software() -> str:
    """``linecaster <release>``: what wrote the file."""
    return f"{SOFTWARE} {version()}"


def record(m: ModelInfo) -> dict[str, Any]:
    """The step record of ``m``: the identifying fields that are set, in ``RECORD_KEYS`` order."""
    out: dict[str, Any] = {}
    for k in RECORD_KEYS:
        v = getattr(m, k)
        if v is None or (k == "settings" and not v):
            continue
        out[k] = v
    return out


def from_record(d: dict[str, Any]) -> ModelInfo:
    """A ``ModelInfo`` from a step record (unknown keys are ignored; ``step``/``name`` default to ``unknown``)."""
    kw: dict[str, Any] = {k: str(d[k]) for k in RECORD_KEYS if k != "settings" and d.get(k) is not None}
    kw.setdefault("step", "unknown")
    kw.setdefault("name", "unknown")
    settings = d.get("settings")
    if settings is not None:
        kw["settings"] = settings if isinstance(settings, dict) else {"value": settings}
    return ModelInfo(**kw)


def label(m: ModelInfo) -> str:
    """What ran, in one word: the preset edition when it ran as one, else the model's name."""
    return m.preset or m.name


def summary(m: ModelInfo) -> str:
    """``step: name@revision`` for people (PAGE ``Comments``), with the preset edition when it ran as one."""
    out = f"{m.step}: {m.name}" + (f"@{m.revision}" if m.revision else "")
    return out + (f" (preset {m.preset})" if m.preset else "")


def category(m: ModelInfo) -> str:
    """ALTO's ``processingCategory``."""
    return "contentGeneration" if m.step in GENERATING_STEPS else "contentModification"


def processed_at(m: ModelInfo) -> str | None:
    """When the step ran, if the step recorded it (``measurements["datetime"]``, ISO 8601), else None."""
    v = m.measurements.get("datetime")
    if isinstance(v, str) and (_DATETIME.match(v) or _DATE.match(v)):
        return v
    return None


def is_datetime(v: str) -> bool:
    return bool(_DATETIME.match(v))


# ------------------------------------------------------------------ values as text

def encode_value(v: Any) -> str:
    """A setting's value as text: strings as they are unless they would read back as something else (then
    as JSON), everything else as JSON. ``decode_value`` inverts it."""
    if isinstance(v, str):
        try:
            json.loads(v)
        except ValueError:
            return v
        return json.dumps(v, ensure_ascii=False)
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=str)


def decode_value(s: str) -> Any:
    try:
        return json.loads(s)
    except ValueError:
        return s


def dumps(d: dict[str, Any]) -> str:
    """A step record as compact JSON, keys in record order (values that JSON cannot hold as text)."""
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"), default=str)
