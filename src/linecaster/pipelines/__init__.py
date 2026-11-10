"""The pipeline shapes, each in a file of this package named like its pipeline script and its pipeline id
(``linecaster.pipelines.transcribe_modular``: ``pipelines/transcribe_modular.py``, ``transcribe_modular.v1``).

A shape has its command line's help text (its docstring), the options it adds (``options(ap)``), the engines the
parsed options ask for (``models(a)``), its blocks (``pipeline(a, script)``), its pipeline id (``PIPELINE``) and,
when recipes fill it, its slots (``SLOTS``): what ``linecaster.runtime.run.main`` takes. The pipeline script of the
same name gives it an environment (its PEP 723 block) and its command line; a derivative's script imports a shape
the same way and can lay its own defaults over its options:

    from linecaster.pipelines import transcribe_modular as shape
    from linecaster.runtime import run

    if __name__ == "__main__":
        run.main(__file__, shape.__doc__, shape.options, shape.models, shape.pipeline, shape.PIPELINE, shape.SLOTS)

Importing a shape imports blocks and the runtime, never an engine (blocks and backends load their engines in
``warm_up``), so tests and the docs build them in linecaster's own environment (``run.describe``).
"""
from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

from ..errors import PipelineConfigError


def shapes() -> dict[str, ModuleType]:
    """Every pipeline shape of this package by its pipeline id."""
    found = {}
    for info in pkgutil.iter_modules(__path__):
        module = importlib.import_module(f"{__name__}.{info.name}")
        if isinstance(getattr(module, "PIPELINE", None), str):
            found[module.PIPELINE] = module
    return found


def shape(pipeline_id: str) -> ModuleType:
    """The pipeline shape with the pipeline id ``pipeline_id`` (``transcribe_modular.v1``); a ``PipelineConfigError``
    names the known ones when there is none."""
    found = shapes()
    if pipeline_id not in found:
        raise PipelineConfigError(f"no pipeline {pipeline_id!r} in linecaster.pipelines (known: "
                                  f"{', '.join(sorted(found))})")
    return found[pipeline_id]
