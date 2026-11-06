"""Normalization step engines: character fidelity *as written* -> *normalized*, on ``Line.normalized``,
``Paragraph.normalized`` and each table cell's ``normalized`` (``Region.extra["table"]``; the as-written texts are
never touched)."""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from ..data.transcription import Transcription
from ..text.variants import normalize
from .base import RuleEngine, ScriptDispatch, Strategy


class TextNormalization(RuleEngine):
    """A page-unit normalization: ``normalize(text)`` on every recognized line, every paragraph and every table
    cell (its ``normalized`` next to its ``text``)."""

    def normalize(self, text: str) -> str:
        raise NotImplementedError

    def __call__(self, t: Transcription, **options) -> Transcription:
        o = self.configured(options)
        changed = 0
        for item in (*t.lines, *t.paragraphs):
            if item.text is None:
                continue
            item.normalized = self.normalize(item.text)
            changed += item.normalized != item.text
        for r in t.regions:
            for cell in (r.extra.get("table") or {}).get("cells") or []:
                cell["normalized"] = self.normalize(cell.get("text") or "")
                changed += cell["normalized"] != (cell.get("text") or "")
        t.steps.append(self.step_info(o, measurements={"changed": changed}))
        return t


class LatinHistoricNormalizationEngine(TextNormalization):
    """The explicit mapping table of ``linecaster.text.variants`` for historic Latin print: long s, ligatures, r
    rotunda and superscript e over a, o, u folded; æ, œ, ø, å and ß stay; NFC, never NFKC; spelling is never
    modernized."""

    engine_id: ClassVar[str] = "normalization.latin-historic.v1"
    step = "normalization"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["normalized"]}
    scripts: ClassVar[tuple[str, ...]] = ("Latn",)

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

    def normalize(self, text: str) -> str:
        return normalize(text)


class ByScriptNormalizationEngine(TextNormalization):
    """Normalization by script: each run of a text (characters of one script, with the Common and Inherited ones
    after them) normalized by the strategy for its script, the rest by the default strategy (``"*"``). A preset
    names the strategies in ``by_script``."""

    engine_id: ClassVar[str] = "normalization.by-script.v1"
    step = "normalization"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["normalized"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        strategies: dict[str, Strategy] = Field(description="ISO 15924 script code, or * for every other script -> "
                                                            "the strategy (a preset's by_script, resolved)")

    def __init__(self, **options):
        super().__init__(**options)
        self.dispatch = ScriptDispatch(self.options.strategies, step=self.step)

    def normalize(self, text: str) -> str:
        return "".join(s.normalize(run) for s, run in self.dispatch.runs(text))
