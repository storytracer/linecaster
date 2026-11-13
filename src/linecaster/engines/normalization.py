"""Normalization step engines: character fidelity *as written* -> *normalized*, as ``normalized`` edits of the lines,
the paragraphs and the table cells (the as-written texts are never touched)."""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from ..data.refs import cell as cell_ref
from ..data.transcription import Edit, Transcription
from ..text.recomposition import paragraphs
from ..text.typography import AS_WRITTEN
from ..text.variants import normalize
from .base import RuleEngine, ScriptDispatch, Strategy


class TextNormalization(RuleEngine):
    """A page-unit normalization: ``normalize(text)`` of every recognized line (as written: its ``nfc`` and
    ``joined`` edits applied), every paragraph of the latest recomposition and every cell of each region's table, an
    ``Edit`` of kind ``normalized`` where it differs (a cell as ``<region>/r<row>c<col>``)."""

    def normalize(self, text: str) -> str:
        raise NotImplementedError

    def __call__(self, t: Transcription, **options) -> Transcription:
        o = self.configured(options)
        a = self.annotate(t, o)
        changed = 0

        def edit(target: str, text: str) -> None:
            nonlocal changed
            normalized = self.normalize(text)
            if normalized != text:
                t.edits.append(Edit(annotator=a, target=target, kind="normalized", text=normalized))
                changed += 1

        for ln in t.lines:
            text = t.text_of(ln, AS_WRITTEN)
            if text is not None:
                edit(ln.id, text)
        for p in paragraphs(t):
            edit(p.id, p.text)
        for target in dict.fromkeys(tb.target for tb in t.tables):
            for cell in t.table(target).cells:
                edit(cell_ref(target, cell.start_row, cell.start_col), cell.text)
        t.annotators[a].measurements.update({"changed": changed})
        return t


class LatinHistoricNormalizationEngine(TextNormalization):
    """Normalizes historic Latin print by the explicit mapping table of ``linecaster.text.variants``.

    Long s, ligatures, r rotunda and superscript e over a, o, u are folded; æ, œ, ø, å and ß stay; NFC, never
    NFKC; spelling is never modernized. Every recognized line, paragraph and table cell whose normalized text differs
    gets a ``normalized`` edit; the annotator records how many (``changed``).

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "normalization.latin-historic.v1"
    step = "normalization"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["normalized"]}
    scripts: ClassVar[tuple[str, ...]] = ("Latn",)

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

    def normalize(self, text: str) -> str:
        return normalize(text)


class ByScriptNormalizationEngine(TextNormalization):
    """Normalizes each run of a text by the strategy for its script.

    A run is the characters of one script with the Common and Inherited ones after them; a script without a
    strategy of its own goes to the default strategy (``"*"``). A preset names the strategies in ``by_script``.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

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
