"""Layout step engines without a model."""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from ..data.transcription import Region, Transcription
from .base import RuleEngine


class SingleRegionLayoutEngine(RuleEngine):
    """Makes the whole page one region, without layout analysis.

    Plain OCR: the transcription's regions are replaced by one region
    covering the page image, reading order 0, score 1; a line step on the whole page and the ``LineAssigner`` then put
    every line into it, and no table or formula regions exist. A layout engine like the model ones (``__call__(image,
    transcription)``, the page image as an RGB array), built in and in the pipeline's process only. Records a layout
    ``StepInfo``.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "layout.single-region.v1"
    step = "layout"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["regions", "reading_order"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        label: str = Field("text", description="the region's label")
        region_id: str = Field("page", description="the region's id")

    def __call__(self, image, t: Transcription, **options) -> Transcription:
        o = self.configured(options)
        height, width = image.shape[:2]
        w, h = float(width), float(height)
        t.regions = [Region(id=o.region_id, label=o.label, polygon=[[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]],
                            bbox=[0.0, 0.0, w, h], score=1.0, reading_order=0)]
        t.steps.append(self.step_info(o))
        return t
