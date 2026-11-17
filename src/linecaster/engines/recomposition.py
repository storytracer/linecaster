"""Recomposition step engines: running text from the visual rows of the text regions (``Transcription.paragraphs``)."""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from linecaster.data.geometry.frames import HORIZONTAL_LR, to_frame
from linecaster.data.transcription import DECISIONS, Decision, Line, Link, Paragraph, ParagraphRow, Transcription
from linecaster.data.policy import TEXT_LABELS
from linecaster.text import recomposition as R
from linecaster.text.typography import hidden
from linecaster.engines.base import RuleEngine, ScriptDispatch, Strategy

#: the region labels whose regions are recomposed into one paragraph: headings
SINGLE_LABELS = ("title", "section_header")
#: the one label whose paragraphs continue and are continued (into the next text region, onto the next page)
RUNNING_LABEL = "text"


def geometric(lines: list[Line]) -> bool:
    """Whether every line has a box or a polygon (else the transcription is text-only: a delivered plain text, a
    VLM's page)."""
    return all(ln.polygon or ln.box for ln in lines)


def rows_of(t: Transcription, lines: list[Line]) -> tuple[list[R.Row], list[list[str]]]:
    """A region's visual rows and the ids of the lines on each: with geometry ``linecaster.text.recomposition.
    region_rows`` (the lines of one visual row side by side), without each line a row of its own, in reading
    order."""
    if geometric(lines):
        return R.region_rows(t, lines), R.row_lines(t, lines)
    ranks = t.line_ranks()
    ordered = sorted(lines, key=lambda ln: ranks[ln.id])
    return [R.Row(t.text_of(ln) or "", None, i) for i, ln in enumerate(ordered)], [[ln.id] for ln in ordered]


def in_direction(rows: list[R.Row], rtl: bool, direction: str | None) -> tuple[list[R.Row], bool]:
    """A region's rows as the margins see them, and whether they run right to left: as they are with ``rtl`` (the
    option) or without a recorded ``direction``; else their boxes in the direction's frame
    (``linecaster.data.geometry.frames``: right to left mirrored, vertical columns as rows), left to right there."""
    if rtl or direction in (None, HORIZONTAL_LR):
        return rows, rtl
    return [R.Row(r.text, to_frame(r.bbox, direction) if r.bbox is not None else None, r.index) for r in rows], False


def digits_only(made: list[R.Paragraph]) -> bool:
    """A region of one paragraph without a letter (a page number, whatever the layout called it): it stands alone,
    and a paragraph open before it stays open, so a sentence continues over the page break."""
    return len(made) == 1 and not any(ch.isalpha() for ch in made[0].text)


class _Open:
    """A paragraph that may run on: the last paragraph of its chain (``Paragraph``), on which page, and the chain's
    text so far with its open end (``R.Paragraph``: what the next decision reads)."""

    def __init__(self, paragraph: Paragraph, page: int, chain: R.Paragraph, t: Transcription):
        self.paragraph, self.page, self.chain, self.t = paragraph, page, chain, t


class UnicodeParagraphsEngine(RuleEngine):
    """Recomposes the rows of each text region into paragraphs from geometry and Unicode's character properties.

    ``linecaster.text.recomposition``: the rows of each text region joined into
    paragraphs, the typesetter's division marks removed, from geometry and Unicode's character properties (line,
    word and sentence breaks), never from a language name; the document's own words decide the one ambiguous case
    (a hyphen that may belong to the word). A paragraph left open at the end of a text region continues in the next
    one, and at the foot of a page on the next page of the item (a region of digits only between them, a page
    number, does not close it); the pages of an item share the lexicon, growing page by page in order. Without
    geometry (a text-only transcription) a region is one paragraph, decided by the character rules alone. Covers
    every script whose text runs in horizontal lines.

    Each page's paragraphs are ranges (``Paragraph``, ids ``<region id>_p<n>``, ``p<n>`` on a page without regions)
    by the call's annotator of that page, made anew by each call; each decision is recorded on its paragraph
    (``Paragraph.decisions``); a continuation links the two paragraphs (``runs_into`` on the first, ``continues`` on
    the second, ``<page id>#<id>`` across pages) and removes the division mark it decided on from the first one's
    text. Regions a status puts nowhere (removed, suppressed, duplicate) are left out.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "paragraphs.unicode.v1"
    step = "paragraphs"
    capabilities: ClassVar[dict] = {"unit": "item", "produces": ["paragraphs"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        rtl: bool = Field(False, description="the writing direction is right to left (start and end margins); "
                                             "False: each region's recorded direction (horizontal-rl, or a vertical "
                                             "one, whose rows are columns), else left to right")
        convention_marks: str = Field("¬", description="characters a transcription convention writes for a "
                                                       "line-end hyphen, besides Unicode's hyphens")
        indent: float = Field(0.8, description="a row indented this many ems from the start margin starts a "
                                               "paragraph; a region whose first row is, continues none")
        gap_leading: float = Field(0.6, description="a gap above a row larger than this share of the leading ...")
        gap_height: float = Field(0.5, description="... and than this share of the taller row's height is a blank "
                                                   "line: a paragraph break")
        short_row: float = Field(1.5, description="in justified text a row ending this many ems short of the end "
                                                  "margin ...")
        short_row_width: float = Field(0.25, description="... and this share of the region's width ends its "
                                                         "paragraph")
        end_margin: float = Field(0.6, description="a row ending within this many ems of the end margin reaches it "
                                                   "(justification; a paragraph that reaches it may run on)")
        justified_rows: int = Field(3, description="a region of at least this many rows ...")
        justified_share: float = Field(0.6, description="... of which this share reach the end margin is justified")

    # ---------------------------------------------------------------- decisions (recomposition.Rules)
    def resolve_mark(self, prev_text: str, next_text: str, lexicon: R.Lexicon | None = None) -> tuple[bool, str]:
        return R.resolve_mark(prev_text, next_text, lexicon, self.options.convention_marks)

    def kept_reason(self, prev_text: str, next_text: str, hyphenated: str = "") -> str:
        return R.kept_reason(prev_text, next_text, hyphenated)

    def separator(self, prev_text: str, next_text: str) -> str:
        return R.separator(prev_text, next_text)

    @staticmethod
    def thresholds(o: BaseModel) -> R.Thresholds:
        return R.Thresholds(indent=o.indent, gap_leading=o.gap_leading, gap_height=o.gap_height,
                            short_row=o.short_row, short_row_width=o.short_row_width, end_margin=o.end_margin,
                            justified_rows=o.justified_rows, justified_share=o.justified_share,
                            marks=o.convention_marks)

    # ---------------------------------------------------------------- the item
    def __call__(self, pages: list[Transcription], page_ids: list[str] | None = None,
                 **options) -> list[Transcription]:
        """The paragraphs of every page of one item, in order (a page alone is an item of one page). ``page_ids``
        name the pages in the references across pages (``<page id>#<id>``; without them ``#1``, ``#2``, ...)."""
        o = self.configured(options)
        return self.recompose(pages, self, o, page_ids)

    def recompose(self, pages: list[Transcription], rules, o: BaseModel, page_ids: list[str] | None = None,
                  record: BaseModel | None = None) -> list[Transcription]:
        """The paragraphs of every page, the decisions made by ``rules`` (this engine, or a by-script engine that
        routes them), the geometry read with ``o``'s thresholds; each page's annotator is ``rules``' with
        ``record`` as its settings (``o`` by default)."""
        th = self.thresholds(o)
        lexicon = R.Lexicon(th.marks)
        # without ids, pages are named by their position (#1, #2, ...), as the DocumentBuilder names them
        ids = list(page_ids) if page_ids is not None else [f"#{k + 1}" for k in range(len(pages))]
        if len(ids) != len(pages):
            raise ValueError(f"{len(pages)} pages, {len(ids)} page ids")
        open_: _Open | None = None
        for k, t in enumerate(pages):
            a = t.add_annotator(rules.annotator(record if record is not None else o))
            stats = R.Stats()
            by_region: dict[str | None, list[Line]] = {}
            for ln in t.lines:
                by_region.setdefault(t.region_of(ln), []).append(ln)
            regions = [r for r in t.ordered_regions() if not hidden(t, r.id)]
            units = [(r.id, t.label(r.id), t.formula(r.id) is not None or t.table(r.id) is not None,
                      by_region.get(r.id, [])) for r in regions]
            if not t.regions and t.lines and not geometric(t.lines):
                units = [(None, "text", False, list(t.lines))]          # a text-only page: one region
            for _rid, _label, _x, lines in units:
                lexicon.add("\n".join(row.text for row in rows_of(t, lines)[0]))
            for rid, label, structured, lines in units:
                if structured or label not in TEXT_LABELS:
                    open_ = None              # a table, formula or picture ends the running text
                    continue
                label = TEXT_LABELS[label]
                rows, on_row = rows_of(t, lines)
                rows, rtl = in_direction(rows, o.rtl, t.direction(rid if rid is not None else ""))
                made = R.reflow_rows(rows, rtl, lexicon, label in SINGLE_LABELS, stats, rules, th)
                if not made:
                    continue
                own = [Paragraph(annotator=a, id=f"{rid}_p{n}" if rid is not None else f"p{n}",
                                 parts=[rid] if rid is not None else [],
                                 rows=[ParagraphRow(lines=on_row[s.row]) for s in p.spans],
                                 decisions=[d for d in p.decisions if d.kind in DECISIONS])
                       for n, p in enumerate(made)]
                t.ranges.extend(own)
                if digits_only(made):
                    continue
                nonempty = [row for row in rows if row.text.strip()]
                m = R.Margins.of(nonempty, rtl, th) if all(row.bbox is not None for row in nonempty) else None
                if (open_ is not None and label == RUNNING_LABEL
                        and R.continues(open_.chain, rows[made[0].spans[0].row], m, rtl, th)):
                    self._continue(open_, k, t, own[0], made[0], ids, lexicon, stats, rules, th)
                    if len(made) == 1 and made[0].open_end:
                        open_.paragraph, open_.page, open_.t = own[0], k, t
                        continue
                open_ = None
                for p, para in zip(own, made):
                    if para.open_end and label == RUNNING_LABEL:
                        open_ = _Open(p, k, R.Paragraph(para.text, open_end=True), t)
            t.annotators[a].measurements.update({"paragraphs": stats.paragraphs,
                                                 "continuations": stats.continuations})
        return pages

    @staticmethod
    def _continue(open_: _Open, page: int, t: Transcription, nxt: Paragraph, made: R.Paragraph, ids: list, lexicon,
                  stats, rules, th: R.Thresholds) -> None:
        """``open_``'s paragraph runs on into ``nxt`` (on page ``page``, transcription ``t``): the continuation and
        the links both ways. What joins the pieces, a division mark included, is the output strategy's."""
        prev = open_.paragraph
        last = len(prev.rows) - 1
        reason = "division_mark" if R.ends_with_mark(open_.chain.text, th.marks) else "end_margin"
        joined, _sep, _decision = R.join(open_.chain, made, lexicon, stats, rules, th)
        prev.decisions.append(Decision(kind="continuation", reason=reason, row=last))
        same_page = open_.page == page
        open_.t.links.append(Link(annotator=prev.annotator, kind="runs_into", source=prev.id,
                                  target=R.ref(None if same_page else ids[page], nxt.id)))
        t.links.append(Link(annotator=nxt.annotator, kind="continues", source=nxt.id,
                            target=R.ref(None if same_page else ids[open_.page], prev.id)))
        open_.chain = R.Paragraph(joined, open_end=made.open_end)
        stats.continuations += 1
        stats.paragraphs -= 1


class ByScriptParagraphsEngine(RuleEngine):
    """Recomposes an item with each decision at a row end made by the strategy for the script around it.

    A decision (a division mark, the separator between two rows) goes to the strategy for the script of the
    characters before the row end, else after it; a script without a strategy of its own goes to the default
    strategy (``"*"``), which also recomposes the item. A preset names the strategies in ``by_script``.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "paragraphs.by-script.v1"
    step = "paragraphs"
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

    def kept_reason(self, prev_text: str, next_text: str, hyphenated: str = "") -> str:
        strategy = self.dispatch.at(prev_text, next_text)
        return getattr(strategy, "kept_reason", R.kept_reason)(prev_text, next_text, hyphenated)

    def separator(self, prev_text: str, next_text: str) -> str:
        return self.dispatch.at(prev_text, next_text).separator(prev_text, next_text)

    def __call__(self, pages: list[Transcription], page_ids: list[str] | None = None,
                 **options) -> list[Transcription]:
        o = self.configured(options)
        default = self.dispatch.default
        default.recompose(pages, self, default.options, page_ids, record=o)
        return pages
