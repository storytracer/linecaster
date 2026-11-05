"""Composition step engines: the document of a page (``Transcription.docling``)."""
from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..data.transcription import Transcription
from .base import RuleEngine


class DoclingCompositionEngine(RuleEngine):
    """A DoclingDocument from a page's regions, lines and tables (``linecaster.formats.docling.DocumentBuilder``):
    titles and section headers at their heading levels, text items with Docling's labels, page headers and
    footers in the furniture layer, tables with their cells, formulas, pictures with the text read inside them,
    optionally one section group per heading; the map of items to regions in ``extra["docling_region_of"]``.
    ``text``: one visual row per line (``lines``), or the rows recomposed into paragraphs (``reflow``)."""

    engine_id: ClassVar[str] = "composition.docling.v1"
    step = "composition"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["document"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        text: Literal["lines", "reflow"] = Field("lines", description="a text item's text: its rows as laid out "
                                                                      "(lines), or recomposed into paragraphs "
                                                                      "(reflow)")
        sections: bool = Field(False, description="every heading opens a section group up to the next heading")
        rtl: bool = Field(False, description="the writing direction is right to left (reflow's margins)")

    def __call__(self, t: Transcription, name: str = "page", **options) -> Transcription:
        """The page's document, named ``name`` (the page id)."""
        from ..formats.docling import REGION_MAP_KEY, DocumentBuilder, docling_dict
        from ..text.recomposition import Stats

        o = self.configured(options)
        stats = Stats()
        b = DocumentBuilder(name, text=o.text, sections=o.sections, rtl=o.rtl, stats=stats)
        b.add_page(t)
        t.docling = docling_dict(b.build())
        t.extra[REGION_MAP_KEY] = dict(b.region_of)
        measured = {"paragraphs": stats.paragraphs, "continuations": stats.continuations,
                    "marks_removed": stats.marks_removed, "marks_kept": stats.marks_kept} if o.text == "reflow" else {}
        t.steps.append(self.step_info(o, measured))
        return t
