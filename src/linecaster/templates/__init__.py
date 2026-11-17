"""The pipeline templates, each in a file of this package named like its pipeline script and its pipeline id
(``linecaster.templates.transcribe_modular``: ``pipelines/transcribe_modular.py``, ``transcribe_modular.v1``).

A template has its command line's help text (its docstring), the options it adds (``options(ap)``), the engines the
parsed options ask for (``models(a)``), its components (``pipeline(a, script)``), its pipeline id (``PIPELINE``) and,
when recipes fill it, its slots (``SLOTS``): what ``linecaster.execution.run.main`` takes. The pipeline script of the
same name gives it an environment (its PEP 723 block) and its command line; a downstream project's script imports a template
the same way and can lay its own defaults over its options:

    from linecaster.templates import transcribe_modular as template
    from linecaster.execution import run

    if __name__ == "__main__":
        run.main(__file__, template.__doc__, template.options, template.models, template.pipeline, template.PIPELINE, template.SLOTS)

Importing a template imports components and the runtime, never an engine (components and backends load their engines in
``warm_up``), so tests and the docs build them in linecaster's own environment (``run.describe``).
"""
from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

from linecaster.errors import PipelineConfigError


def templates() -> dict[str, ModuleType]:
    """Every pipeline template of this package by its pipeline id."""
    found = {}
    for info in pkgutil.iter_modules(__path__):
        module = importlib.import_module(f"{__name__}.{info.name}")
        if isinstance(getattr(module, "PIPELINE", None), str):
            found[module.PIPELINE] = module
    return found


def template(pipeline_id: str) -> ModuleType:
    """The pipeline template with the pipeline id ``pipeline_id`` (``transcribe_modular.v1``); a ``PipelineConfigError``
    names the known ones when there is none."""
    found = templates()
    if pipeline_id not in found:
        raise PipelineConfigError(f"no pipeline {pipeline_id!r} in linecaster.templates (known: "
                                  f"{', '.join(sorted(found))})")
    return found[pipeline_id]
