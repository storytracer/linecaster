"""linecaster-tesseract's catalogue documents (``specs/catalog.md``): ``models/``, ``presets/``, ``evidence/`` and
``catalog.lock`` in this folder, registered in the entry-point group ``linecaster.catalog``."""
from pathlib import Path


def directory() -> Path:
    return Path(__file__).resolve().parent
