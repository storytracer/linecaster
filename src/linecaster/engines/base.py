"""The engine protocol of the rule-based steps (image, normalization, typography, recomposition, composition), and
the dispatch of their decisions by script.

A rule-based engine (a **strategy**) is a class like a model engine, without weights:

* ``engine_id`` (its code id, e.g. ``typography.ratios.v1``), ``step``, ``capabilities`` (``unit``, ``produces``),
  ``scripts`` (the ISO 15924 scripts it covers, ``("*",)`` for all) and ``Options`` (a Pydantic model whose fields
  have descriptions and today's values as defaults);
* constructed with its options as keyword arguments (``Engine(**preset.options)``), ``load()`` (nothing to load);
* a call per unit. Page unit: ``__call__(t: Transcription, **options) -> Transcription``. Item unit:
  ``__call__(pages: list[Transcription], **options) -> list[Transcription]``, the transcriptions of one item's pages
  in order (a page is an item of one page). The image step's engines take the page image's bytes instead:
  ``__call__(data: bytes, **options) -> (bytes, info)``. Options given to a call override the engine's own for that
  call. The engine records what it did as a ``StepInfo`` on each transcription (``step_info``).

They run in the pipeline's process only (``linecaster.catalog.registry.IN_PROCESS_ONLY``): rules are cheaper than a
request.

**Dispatch by script.** A by-script engine (``recomposition.by-script.v1``, ``normalization.by-script.v1``) is
constructed with ``strategies``: ISO 15924 code -> strategy, and ``"*"`` -> the default strategy, each as
``Strategy`` (the engine as ``module:Class``, its options, the preset edition it came from), which a preset's
``by_script`` resolves to. ``ScriptDispatch`` builds them and routes each decision to the strategy of the script
around it (``scripts.Classifier.at``: the characters before a row end, else after it), and each run of a text to
the strategy of its script (``Classifier.runs``); a script without a strategy of its own goes to the default.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from ..data.transcription import StepInfo
from . import scripts as S


class RuleEngine:
    """Base of the built-in rule-based engines: options, ``load()``, the options of a call, the step record. A
    subclass states ``engine_id``, ``step``, ``capabilities``, ``scripts`` and ``Options`` in its own body (the docs
    read them from the source) and defines ``__call__`` for its unit."""

    engine_id: ClassVar[str]
    step: ClassVar[str]
    capabilities: ClassVar[dict]
    scripts: ClassVar[tuple[str, ...]] = (S.ALL,)

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

    def __init__(self, **options):
        self.options = self.Options(**options)

    def load(self) -> None:
        """Nothing to load: the rules are code."""

    def configured(self, options: dict[str, Any]) -> BaseModel:
        """The engine's options with those of one call over them, validated."""
        return self.Options(**{**self.options.model_dump(), **options}) if options else self.options

    def step_info(self, options: BaseModel | None = None, measurements: dict | None = None,
                  name: str | None = None) -> StepInfo:
        """The ``StepInfo`` of one call: the step, the engine (also the name, when no library is named), the
        options as settings, ``measurements`` (``linecaster.data.MEASUREMENTS``)."""
        o = options if options is not None else self.options
        return StepInfo(step=self.step, name=name or self.engine_id, engine=self.engine_id,
                        settings=o.model_dump(mode="json"), measurements=measurements or {})

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.engine_id}>"


class Strategy(BaseModel):
    """One strategy of a by-script engine: the engine (``module:Class``) and its options, as a preset gives them."""

    model_config = ConfigDict(extra="forbid")

    engine: str = Field(description="the engine's class, module:Class")
    options: dict[str, Any] = Field(default_factory=dict, description="its options")
    preset: str | None = Field(None, description="the preset edition it came from: id@edition")
    preset_sha256: str | None = Field(None, description="that edition's hash")


def engine_class(spec: str):
    """The class ``module:Class`` names."""
    module, _, name = spec.partition(":")
    return getattr(import_module(module), name)


class ScriptDispatch:
    """Strategies by script and a default (``"*"``), and the routing of decisions and texts to them.

    ``strategies``: ISO 15924 code (or ``"*"``) -> a strategy object, or a ``Strategy`` (or its dict) to construct
    one from. Each strategy must cover its script (its ``scripts``); the default must exist."""

    def __init__(self, strategies: dict[str, Any], step: str | None = None):
        if S.ALL not in strategies:
            raise ValueError(f"a by-script engine needs a default strategy ('*'); it has {sorted(strategies)}")
        built = {}
        for code, s in strategies.items():
            S.check_code(code)
            if isinstance(s, (dict, Strategy)):
                spec = s if isinstance(s, Strategy) else Strategy(**s)
                s = engine_class(spec.engine)(**spec.options)
                s.load()
            if step is not None and getattr(s, "step", step) != step:
                raise ValueError(f"strategy for {code} is a {s.step} engine, not {step}")
            if not S.covers(getattr(s, "scripts", (S.ALL,)), code):
                raise ValueError(f"strategy {getattr(s, 'engine_id', s)!r} for {code} covers only {s.scripts}")
            built[code] = s
        self.default = built.pop(S.ALL)
        self.by_script = built
        self.classify = S.Classifier(built)

    def strategy(self, script: str):
        """The strategy of ``script`` (``"*"`` or one without its own: the default)."""
        return self.by_script.get(script, self.default)

    def at(self, before: str, after: str):
        """The strategy that decides between ``before`` and ``after``."""
        return self.strategy(self.classify.at(before, after)) if self.by_script else self.default

    def runs(self, text: str) -> list[tuple[Any, str]]:
        """``text`` cut into runs, each with the strategy of its script."""
        if not self.by_script:
            return [(self.default, text)] if text else []
        return [(self.strategy(s), run) for s, run in self.classify.runs(text)]
