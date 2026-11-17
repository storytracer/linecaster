"""``RuleComponent``: the base of the components of the rule-based steps (image, typography, recomposition,
composition), each on a built-in engine (``linecaster.engines``) that runs in the pipeline's process.

A rule component takes its engine like a model component: a catalog preset (by its id: ``"ratios"``)
or an engine spec, ``InProcess("module:Class", **options)``; ``options`` go over either (they
are recorded as the backend's ``overrides``, as ``--set`` records them for model steps). There is no backend
choice: rules are cheaper than a request, so a ``Served`` backend is refused. Each call of the engine adds one
``Annotator`` to the transcription; the component stamps it with the preset and its hash, ``seconds`` and
``datetime``, as ``ModelComponent`` does for model steps.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, ClassVar

from linecaster.backends import InProcess
from linecaster.data.transcription import Annotator
from linecaster.errors import CatalogError, PipelineConfigError
from linecaster.core.page import PageComponent


def rule_backend(preset, step: str, options: dict[str, Any] | None = None) -> InProcess:
    """The in-process backend of a rule component of ``step``: from a preset ref, or the ``InProcess`` given (copied),
    with ``options`` over its options; the engine's step and options checked (``check_engine``)."""
    if isinstance(preset, str):
        from linecaster.catalog.registry import catalog

        try:
            found = catalog().resolve(preset).content.get("step")
        except (CatalogError, ValueError) as e:
            raise PipelineConfigError(f"{step}: {e}") from None
        if found != step:
            raise PipelineConfigError(f"{step}: preset {preset!r} is a {found} preset")
        backend = InProcess.from_preset(preset)
    elif isinstance(preset, InProcess):
        backend = InProcess(preset.spec, **preset.kwargs)
        backend.preset, backend.preset_sha256, backend.overrides = preset.preset, preset.preset_sha256, preset.overrides
    elif getattr(preset, "served", False):
        raise PipelineConfigError(f"{step}: rule-based steps run in the pipeline's process only (no Served backend)")
    else:
        raise PipelineConfigError(f"{step}: give a preset (id) or an engine spec (InProcess), not {preset!r}")
    if options:
        backend.kwargs = {**backend.kwargs, **options}
        backend.overrides = {**(backend.overrides or {}), **options}
    check_engine(backend, step)
    return backend


def check_engine(backend: InProcess, step: str) -> None:
    """The engine's step and options checked now, not when the task starts (built-in engines import cheaply; an
    engine that is not installed here is checked when it loads)."""
    from linecaster.backends import resolve

    try:
        cls = resolve(backend.spec)
    except (ImportError, AttributeError):
        return
    if getattr(cls, "step", step) != step:
        raise PipelineConfigError(f"{step}: {backend.spec} is a {cls.step} engine")
    options = getattr(cls, "Options", None)
    if options is not None:
        try:
            options(**backend.kwargs)
        except ValueError as e:
            raise PipelineConfigError(f"{step}: {backend.spec}: {e}") from None


def stamp(info: Annotator, backend: InProcess, start: float, began: str) -> Annotator:
    """``info`` with the preset it ran as, and ``seconds`` and ``datetime`` (unless the engine set them)."""
    info.measurements.setdefault("seconds", round(time.perf_counter() - start, 4))
    info.measurements.setdefault("datetime", began)
    if backend.preset:
        info.preset, info.preset_sha256 = backend.preset, backend.preset_sha256
    return info


def now() -> tuple[float, str]:
    """The start of a call: a clock for ``seconds``, the time for ``datetime``."""
    return time.perf_counter(), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RuleComponent(PageComponent):
    """Runs a rule-based step's built-in engine on every page, in the pipeline's process, as the base of the rule
    components.

    Subclasses state their catalog ``step`` and implement ``apply(page, t)`` (the engine is ``self.engine``); the
    base stamps every ``Annotator`` the call added with the preset and its hash, ``seconds`` and
    ``datetime``. A page without the transcription passes unchanged (stat ``no_transcription``). There is no
    backend choice: a ``Served`` backend is refused.

    Args:
        preset: the engine: a catalog preset of the component's step (its ``id``)
            or an engine spec, ``InProcess("module:Class", **options)``; a preset of another step, an
            engine of another step or options its engine does not have are refused (``PipelineConfigError``).
        transcription: the transcription it works on.
        options: engine options over the preset's (recorded as the backend's ``overrides``); ``None``: the
            preset's as they are.
    """

    step: ClassVar[str] = "rule"           # the catalog step of the subclass's engines

    def __init__(self, preset, transcription: str = "ocr_new", options: dict[str, Any] | None = None):
        super().__init__()
        self.backend = rule_backend(preset, self.step, options)
        self.transcription, self.options = transcription, dict(options or {})

    def init_params(self) -> dict[str, Any]:
        """The parameters, ``preset`` as the backend it resolved to (engine, options, preset and hash)."""
        out = super().init_params()
        out["preset"] = self.backend
        return out

    @property
    def engine(self):
        return self.backend.model()

    def warm_up(self) -> None:
        self.backend.warm_up()

    def process_page(self, doc, page):
        t = page.transcriptions.get(self.transcription)
        if t is None:
            self.stat_update("no_transcription")
            return page
        start, began = now()
        n = len(t.annotators)
        self.apply(page, t)
        for info in t.annotators[n:]:
            stamp(info, self.backend, start, began)
        return page

    def apply(self, page, t) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def count(self, measurements: dict, keys: tuple[str, ...]) -> None:
        """The component's stats from a step's measurements."""
        for key in keys:
            if measurements.get(key):
                self.stat_update(key, value=measurements[key])
