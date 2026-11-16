"""``Tagger``: classifications of a page's zones in property schemes by a tagging engine (``tagging.*``:
``tagging.geometry.v1``, rules on geometry; ``tagging.chat.v1``, a panel of models behind chat servers)."""
from __future__ import annotations

from typing import Any

from ..base.contract import Contract, parts
from ..base.page import image_bytes
from ..base.rule import RuleBlock


class Tagger(RuleBlock):
    """Classifies the zones of every page in property schemes (``rotated``, ``tiny``, ``multi_column``,
    ``degraded``, ``form``, ...) by a tagging engine, in the pipeline's process.

    Each decision is a classification of the narrowest target (a line, a region, the page) by the engine's annotator,
    with its evidence: the geometry tagger's measurements, or every panel member's answer, as raw outputs; where the
    evidence does not decide, nothing is recorded. The page image is decoded for an engine that reads it (the model
    tagger, which shows the members the page and the target). Reads ``regions`` and ``lines`` (the model tagger: the
    page image and its targets); adds ``tags``. Stats: ``tagged`` and ``undecided`` (classifications recorded and
    targets left undecided, over all schemes). The engine gets the page's id (``page``), which review items name.

    Args:
        preset: the tagger: a catalog preset of the ``tagging`` step (``geometry-tags``) or an engine spec,
            ``InProcess("module:Class", **options)`` (the model tagger, whose panel a run names); a preset of another
            step, an engine of another step or options its engine does not have are refused
            (``PipelineConfigError``).
        transcription: the transcription it classifies.
        options: engine options over the preset's (recorded as the backend's ``overrides``); ``None``: the
            preset's as they are.

    Example:
        Tagger("geometry-tags")
        Tagger(InProcess("linecaster.engines:ChatTaggingEngine", schemes=["degraded"], panel=[...]))
    """

    name = "tagger"
    step = "tagging"
    docs_args = {"preset": "geometry-tags"}
    parts_added = ("tags",)

    def __init__(self, preset, transcription: str = "ocr_new", options: dict[str, Any] | None = None):
        super().__init__(preset, transcription, options)
        from ...backends import resolve

        try:
            cls = resolve(self.backend.spec)
        except (ImportError, AttributeError):
            cls = None
        reads = getattr(cls, "reads", None)
        self.reads_image = bool(getattr(cls, "reads_image", True))
        self.parts_read = tuple(reads(self.backend.kwargs)) if callable(reads) else ("image", "regions", "lines")

    def contract(self) -> Contract:
        t = self._transcription()
        return Contract(unit=self.unit, role=self.role, reads=parts(self.parts_read, t),
                        adds=parts(self.parts_added, t))

    def process_page(self, doc, page):
        self._doc = doc
        try:
            return super().process_page(doc, page)
        finally:
            self._doc = None

    def apply(self, page, t) -> None:
        image = None
        if self.reads_image:
            from ..base.page import decode_rgb

            image = decode_rgb(image_bytes(self._doc))
        self.engine(image, t, page=page.page_id)
        m = t.annotators[-1].measurements
        tagged = sum(n for by in (m.get("tagged") or {}).values() for n in by.values())
        undecided = sum((m.get("undecided") or {}).values())
        for key, value in (("tagged", tagged), ("undecided", undecided)):
            if value:
                self.stat_update(key, value=value)
