"""Fake engines: deterministic, dependency-free CPU engines, one per model step, for tests of blocks, pipelines and
derivatives. They follow the engine protocol (``linecaster.engines.api.Engine``) and are registered under
``fake.<step>.v1`` (the page engine ``fake.recognition.page.v1``) only when ``register_fakes()`` is called (never
through entry points), so they never show up in an installation."""
from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from ..data import Annotator, Cell, Formula, RawOutput, Table, Transcription
from .samples import box


class _Fake:
    """Options, ``load()`` and the step record of a fake engine."""

    engine_id: ClassVar[str]
    step: ClassVar[str]
    capabilities: ClassVar[dict]

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

    def __init__(self, **options):
        self.options = self.Options(**options)
        self.loaded = False

    def load(self) -> None:
        """Nothing to load; records that it was called."""
        self.loaded = True

    def _start(self, t: Transcription) -> int:
        """Appends the call's annotator to ``t``; returns its index."""
        return t.add_annotator(Annotator(step=self.step, name=f"fake-{self.step}", engine=self.engine_id,
                                         backend="fake (cpu)", settings=self.options.model_dump(mode="json")))

    def _done(self, t: Transcription, counted: dict | None = None) -> Transcription:
        """``t`` with the table or formula count (``tables``, ``formulas``) in the call's measurements."""
        if counted is not None:
            t.annotators[-1].measurements = {"tables": counted["tables"]} if "tables" in counted else {
                "formulas": counted["formulas"]}
        return t


def _size(image, t: Transcription) -> tuple[int, int]:
    if image is not None:
        h, w = image.shape[:2]
        return int(w), int(h)
    return int(t.source.image_width or 0), int(t.source.image_height or 0)


class FakeLayoutEngine(_Fake):
    """Lays the page out as a fixed grid of text regions (one region by default), in reading order row by row.

    Args:
        **options: the fields of its ``Options`` (``rows``, ``cols``, ``label``)."""

    engine_id: ClassVar[str] = "fake.layout.v1"
    step: ClassVar[str] = "layout"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["regions", "reading_order"]}

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        rows: int = Field(1, ge=1, description="rows of the grid of regions")
        cols: int = Field(1, ge=1, description="columns of the grid of regions")
        label: str = Field("text", description="the regions' label")

    def __call__(self, image, transcription: Transcription, **params: Any) -> Transcription:
        w, h = _size(image, transcription)
        o = self.options
        cw, rh = w / o.cols, h / o.rows
        a = self._start(transcription)
        for k, (r, c) in enumerate((r, c) for r in range(o.rows) for c in range(o.cols)):
            transcription.add_region(a, f"{o.label}_{k}", [c * cw, r * rh, cw, rh], box(c * cw, r * rh, cw, rh),
                                     label=o.label, role=o.label, confidence=1.0)
        transcription.add_order(a, [r.id for r in transcription.regions[-o.rows * o.cols:]])
        return self._done(transcription)


class FakeLineEngine(_Fake):
    """Finds lines: each region (or the whole page, without regions) split into equal horizontal bands, or the boxes
    it is given (a sample page's known boxes, ``linecaster.testing.sample_boxes``).

    Lines of a region are ``<region id>_l<k>``, lines of a page without regions ``l<k>``, with box, polygon, row
    and reading order.

    Args:
        **options: the fields of its ``Options`` (``split``, ``boxes``)."""

    engine_id: ClassVar[str] = "fake.lines.v1"
    step: ClassVar[str] = "lines"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["lines"]}

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        split: int = Field(2, ge=1, description="bands per region (or per page without regions)")
        boxes: list[list[float]] | None = Field(None, description="line boxes [x, y, width, height] to return "
                                                                  "instead (lines l<k>, no region)")

    def __call__(self, image, transcription: Transcription, **params: Any) -> Transcription:
        o = self.options
        a = self._start(transcription)
        t = transcription
        if o.boxes is not None:
            for k, b in enumerate(o.boxes):
                t.add_line(a, f"l{k}", list(b), box(*b))
            t.add_order(a, lines=[f"l{k}" for k in range(len(o.boxes))], rows=range(len(o.boxes)))
            return self._done(t)
        w, h = _size(image, t)
        areas = [(r.id, r.box) for r in t.ordered_regions()] or [(None, [0, 0, w, h])]
        ids, rows = [], []
        for rid, (x, y, bw, bh) in areas:
            step = int(bh) // o.split
            for k in range(o.split):
                b = [x, y + k * step, bw, step]
                ids.append(t.add_line(a, f"{rid}_l{k}" if rid else f"l{k}", b, box(*b), region=rid).id)
                rows.append(k)
        t.add_order(a, lines=ids, rows=rows)
        return self._done(t)


class FakeRecognitionEngine(_Fake):
    """Recognizes every line as a text made from the line's id (``template``), with a confidence.

    Args:
        **options: the fields of its ``Options`` (``template``, ``confidence``)."""

    engine_id: ClassVar[str] = "fake.recognition.v1"
    step: ClassVar[str] = "recognition"
    capabilities: ClassVar[dict] = {"unit": "line", "produces": ["text", "line_confidences"]}

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        template: str = Field("text of {line}", description="the text of a line: str.format with line (its id), "
                                                             "index (its position), width and height (the page's)")
        confidence: float = Field(0.99, description="every line's confidence")

    def __call__(self, image, transcription: Transcription, **params: Any) -> Transcription:
        w, h = _size(image, transcription)
        a = self._start(transcription)
        for i, ln in enumerate(transcription.lines):
            transcription.read(a, ln, self.options.template.format(line=ln.id, index=i, width=w, height=h),
                               self.options.confidence)
        return self._done(transcription)


class FakePageEngine(_Fake):
    """Reads the whole page as a text-only transcription: one line per line of a text made from the page's size
    (``template``), no geometry, the text kept as its raw output, as a page engine returns it.

    Args:
        **options: the fields of its ``Options`` (``template``)."""

    engine_id: ClassVar[str] = "fake.recognition.page.v1"
    step: ClassVar[str] = "recognition"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["lines", "text", "markdown"]}

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        template: str = Field("# page\n{width}x{height}", description="the page's text: str.format with width and "
                                                                       "height (the page image's)")

    def __call__(self, image, transcription: Transcription, **params: Any) -> Transcription:
        w, h = _size(image, transcription)
        raw = self.options.template.format(width=w, height=h)
        out = Transcription(source=transcription.source.model_copy())
        a = self._start(out)
        o = out.add_output(RawOutput(annotator=a, content=raw))
        for i, text in enumerate(raw.split("\n")):
            out.read(a, out.add_line(a, f"l{i}", output=o), text, output=o)
        out.add_order(a, lines=[ln.id for ln in out.lines])
        return self._done(out)


class FakeTableEngine(_Fake):
    """Gives every table region a one-cell structure holding the region's id.

    Args:
        **options: the fields of its ``Options`` (``label``)."""

    engine_id: ClassVar[str] = "fake.tables.v1"
    step: ClassVar[str] = "tables"
    capabilities: ClassVar[dict] = {"unit": "region", "produces": ["tables", "html"]}

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        label: str = Field("table", description="the label of the regions it reads")

    def __call__(self, image, transcription: Transcription, **params: Any) -> Transcription:
        n = 0
        a = self._start(transcription)
        for r in transcription.regions:
            if transcription.label(r.id) == self.options.label:
                transcription.tables.append(Table(annotator=a, target=r.id, num_rows=1, num_cols=1,
                                                  html=f"<table><tr><td>{r.id}</td></tr></table>",
                                                  cells=[Cell(text=r.id, start_row=0, end_row=1, start_col=0,
                                                              end_col=1, box=list(r.box))]))
                n += 1
        return self._done(transcription, {"tables": n})


class FakeFormulaEngine(_Fake):
    """Reads every formula region as LaTeX naming the region.

    Args:
        **options: the fields of its ``Options`` (``label``)."""

    engine_id: ClassVar[str] = "fake.formulas.v1"
    step: ClassVar[str] = "formulas"
    capabilities: ClassVar[dict] = {"unit": "region", "produces": ["formulas", "latex"]}

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        label: str = Field("formula", description="the label of the regions it reads")

    def __call__(self, image, transcription: Transcription, **params: Any) -> Transcription:
        n = 0
        a = self._start(transcription)
        for r in transcription.regions:
            if transcription.label(r.id) == self.options.label:
                transcription.formulas.append(Formula(annotator=a, target=r.id,
                                                      latex=f"x_{{{r.id.replace('_', '')}}}"))
                n += 1
        return self._done(transcription, {"formulas": n})


#: the fake engines by id
FAKE_ENGINES = {cls.engine_id: f"{cls.__module__.rsplit('.', 1)[0]}:{cls.__name__}"
                for cls in (FakeLayoutEngine, FakeLineEngine, FakeRecognitionEngine, FakePageEngine, FakeTableEngine,
                            FakeFormulaEngine)}


def register_fakes() -> dict[str, str]:
    """Registers the fake engines under their ids (``fake.<step>[.<variant>].v1``), for ``engine_class`` and
    ``engine_ids``.

    Idempotent; the registration lasts for the process (the ids cannot clash with real ones). Returns the ids with
    their classes (``module:Class``).
    """
    from ..catalog import registry

    registry.REGISTERED.update(FAKE_ENGINES)
    return dict(FAKE_ENGINES)
