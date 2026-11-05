"""Recomposition step engines: running text from the visual rows of the text regions (``Transcription.paragraphs``)."""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from ..data.transcription import Line, Paragraph, ParagraphRow, Transcription
from ..formats.docling import TEXT_LABELS, region_rows
from ..text import recomposition as R
from .base import RuleEngine, ScriptDispatch, Strategy

#: the (Docling) labels whose regions are recomposed into one paragraph: headings
SINGLE_LABELS = ("title", "section_header")


def rows_of(lines: list[Line]) -> tuple[list[R.Row], list[list[str]]]:
    """A region's visual rows (``linecaster.formats.docling.region_rows``) and the ids of the lines on each."""
    return region_rows(lines), [[ln.id for ln in lines if ln.row == k] for k in sorted({ln.row for ln in lines})]


class UnicodeRecompositionEngine(RuleEngine):
    """squiddleocr's recomposition (``linecaster.text.recomposition``): the rows of each text region joined into
    paragraphs, the typesetter's division marks removed, from geometry and Unicode's character properties (line,
    word and sentence breaks), never from a language name; the document's own words decide the one ambiguous case
    (a hyphen that may belong to the word). The pages of an item share that lexicon, in order. Covers every
    script whose text runs in horizontal lines.

    Makes the paragraphs of each region; the decisions, the continuation across regions and pages and the
    text-only fallback come with the Recomposer. Options other than the defaults are refused until the rules take
    them as parameters."""

    engine_id: ClassVar[str] = "recomposition.unicode.v1"
    step = "recomposition"
    capabilities: ClassVar[dict] = {"unit": "item", "produces": ["paragraphs"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        rtl: bool = Field(False, description="the writing direction is right to left (start and end margins)")
        convention_marks: str = Field("¬", description="characters a transcription convention writes for a "
                                                       "line-end hyphen, besides Unicode's hyphens")

    # ---------------------------------------------------------------- decisions (recomposition.Rules)
    def resolve_mark(self, prev_text: str, next_text: str, lexicon: R.Lexicon | None = None) -> tuple[bool, str]:
        return R.resolve_mark(prev_text, next_text, lexicon)

    def separator(self, prev_text: str, next_text: str) -> str:
        return R.separator(prev_text, next_text)

    # ---------------------------------------------------------------- the item
    def __call__(self, pages: list[Transcription], **options) -> list[Transcription]:
        return self.recompose(pages, self, self.configured(options))

    def recompose(self, pages: list[Transcription], rules, o: BaseModel) -> list[Transcription]:
        """The paragraphs of every page, the decisions made by ``rules`` (this engine, or a by-script engine that
        routes them)."""
        if o.convention_marks != R.CONVENTION_MARKS:
            raise ValueError(f"{self.engine_id}: convention_marks other than {R.CONVENTION_MARKS!r} are not "
                             "supported yet")
        lexicon = R.Lexicon()
        for t in pages:
            stats = R.Stats()
            by_region: dict[str | None, list[Line]] = {}
            for ln in t.lines:
                by_region.setdefault(ln.region_id, []).append(ln)
            regions = sorted(t.regions, key=lambda r: r.reading_order if r.reading_order is not None else 1 << 30)
            for r in regions:
                lexicon.add("\n".join(row.text for row in rows_of(by_region.get(r.id, []))[0]))
            paragraphs = []
            for r in regions:
                if r.label not in TEXT_LABELS or r.extra.get("formula") is not None or r.extra.get("table") is not None:
                    continue
                rows, on_row = rows_of(by_region.get(r.id, []))
                made = R.reflow_rows(rows, o.rtl, lexicon, TEXT_LABELS[r.label] in SINGLE_LABELS, stats, rules)
                paragraphs += [Paragraph(id=f"{r.id}_p{n}", region_id=r.id, text=p.text,
                                         rows=[ParagraphRow(lines=on_row[s.row], start=s.start, end=s.end)
                                               for s in p.spans])
                               for n, p in enumerate(made)]
            t.paragraphs = paragraphs
            t.steps.append(self.step_info(o, {"paragraphs": stats.paragraphs, "continuations": stats.continuations,
                                              "marks_removed": stats.marks_removed, "marks_kept": stats.marks_kept}))
        return pages


class ByScriptRecompositionEngine(RuleEngine):
    """Recomposition by script: each decision at a row end (a division mark, the separator between two rows) made
    by the strategy for the script around it (the characters before the row end, else after it), the rest by the
    default strategy (``"*"``), which also recomposes the item. A preset names the strategies in ``by_script``."""

    engine_id: ClassVar[str] = "recomposition.by-script.v1"
    step = "recomposition"
    capabilities: ClassVar[dict] = {"unit": "item", "produces": ["paragraphs"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        strategies: dict[str, Strategy] = Field(description="ISO 15924 script code, or * for every other script -> "
                                                            "the strategy (a preset's by_script, resolved)")

    def __init__(self, **options):
        super().__init__(**options)
        self.dispatch = ScriptDispatch(self.options.strategies, step=self.step)

    def resolve_mark(self, prev_text: str, next_text: str, lexicon: R.Lexicon | None = None) -> tuple[bool, str]:
        return self.dispatch.at(prev_text, next_text).resolve_mark(prev_text, next_text, lexicon)

    def separator(self, prev_text: str, next_text: str) -> str:
        return self.dispatch.at(prev_text, next_text).separator(prev_text, next_text)

    def __call__(self, pages: list[Transcription], **options) -> list[Transcription]:
        o = self.configured(options)
        default = self.dispatch.default
        default.recompose(pages, self, default.options)
        for t in pages:
            t.steps[-1] = self.step_info(o, t.steps[-1].measurements)
        return pages
