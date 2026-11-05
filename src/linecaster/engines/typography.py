"""Typography step engines: the hierarchy of a page from its type sizes."""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from ..data.transcription import Transcription
from ..text import typography as T
from .base import RuleEngine


class RatiosTypographyEngine(RuleEngine):
    """squiddleocr's retyper (``linecaster.text.typography``): every rule a ratio to the page's own body type.
    Heading levels from the type size, section headers in body type made text, headlines split off the text
    region they were merged into, drop capitals joined to their line, uncertain page numbers removed. The rules
    cover every script that is set in lines of type sizes.

    Runs today's code with today's thresholds: options other than the defaults are refused until the thresholds
    are its parameters."""

    engine_id: ClassVar[str] = "typography.ratios.v1"
    step = "typography"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["hierarchy"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        page_number_min_conf: float = Field(0.75, description="a page number read with a lower mean character "
                                                              "confidence is removed")
        demote: float = Field(1.2, description="a section header whose rows are less than this many times the body "
                                               "size becomes text")
        split: float = Field(1.6, description="leading rows this many times taller than the rest and the body size "
                                              "are a headline of their own")
        levels: list[tuple[float, int]] = Field([(2.5, 1), (1.7, 2), (0.0, 3)],
                                                description="(ratio to the body size, heading level), highest first: "
                                                            "a heading gets the first level whose ratio it reaches")
        max_headline_rows: int = Field(3, description="at most this many leading rows split off as a headline")
        heading_labels: list[str] = Field(["section_header", "title"], description="the region labels of headings")

    def __call__(self, t: Transcription, **options) -> Transcription:
        o = self.configured(options)
        if o != self.Options():
            raise ValueError(f"{self.engine_id}: options other than the defaults are not supported yet: "
                             f"{o.model_dump(exclude_defaults=True)}")
        T.retype(t)
        t.steps[-1].engine = self.engine_id
        return t
