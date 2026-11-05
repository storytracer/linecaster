"""PP-OCRv6 text detection through PaddleX's ONNX Runtime engine."""
from __future__ import annotations

from typing import ClassVar

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from linecaster.data import Line, ModelInfo, Transcription
from linecaster.data.geometry import BBox, bbox_of, xywh

from .compat import create_predictor, paddle_image
from .crops import crop_bbox, crop_polygon
from .weights import check, resolve

DETECTORS = ("PP-OCRv6_medium_det", "PP-OCRv6_small_det", "PP-OCRv6_tiny_det")


class PaddleTextDetector:
    """DBNet-style detector; ``unclip_ratio`` expands boxes (PaddleOCR's default 1.5; see NOTES "Unclip ratio back to 1.5").

    Given a region, detection runs on its crop: the bounding box with ``pad`` pixels around it and,
    with ``mask``, everything outside the region polygon painted white (a layout analyzer's regions
    in front of the detector, so a neighboring column cannot leak in)."""

    def __init__(self, model_name: str = "PP-OCRv6_medium_det", device: str = "auto", unclip_ratio: float = 1.5,
                 box_thresh: float = 0.6, thresh: float = 0.3, pad: int = 0, mask: bool = False,
                 model_dir: str | None = None):
        self.model_name = model_name
        self.unclip_ratio, self.box_thresh, self.thresh, self.pad, self.mask = unclip_ratio, box_thresh, thresh, pad, mask
        self.predictor = create_predictor(model_name, device, model_dir=model_dir)

    def detect(self, page_image: np.ndarray, region=None) -> list[tuple[np.ndarray, float, str]]:
        """Line polygons (page coordinates), scores and the region id; ``region`` is a linecaster Region."""
        if region is None:
            image, dx, dy, rid = page_image, 0.0, 0.0, ""
        elif self.mask:
            image, dx, dy = crop_polygon(page_image, np.asarray(region.polygon, dtype=float), self.pad)
            rid = region.id
            if image.size == 0:
                return []
        else:
            b = bbox_of(region.polygon)
            image = crop_bbox(page_image, b, self.pad)
            dx, dy, rid = max(b.x0 - self.pad, 0.0), max(b.y0 - self.pad, 0.0), region.id
            if image.size == 0:
                return []
        res = next(iter(self.predictor.predict(paddle_image(image), thresh=self.thresh,
                                                box_thresh=self.box_thresh, unclip_ratio=self.unclip_ratio)))
        lines = []
        for poly, score in zip(res["dt_polys"], res["dt_scores"]):
            pts = np.asarray(poly, dtype=float).reshape(-1, 2) + np.array([int(dx), int(dy)], dtype=float)
            lines.append((pts, float(score), rid))
        return lines


class PaddleLineEngine:
    """linecaster engine model for the lines step: PP-OCRv6 detection on the whole page (default) or,
    with ``per_region``, on each region's crop. Fills ``Transcription.lines`` with geometry (polygon,
    bbox, score); text stays ``None``. Replaces any lines already present. The model files: ``weights`` (a
    catalog pin) or the catalog's newest pin for ``model_name`` (``weights.resolve``)."""

    engine_id: ClassVar[str] = "paddlex.lines.v1"
    step = "lines"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["lines"]}

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid", protected_namespaces=())

        model_name: str = Field("PP-OCRv6_medium_det", description="PaddleX text detector: "
                                                                   "PP-OCRv6_{tiny,small,medium}_det")
        device: str = Field("auto", description="auto, cpu, cuda, tensorrt or coreml (ONNX Runtime providers)")
        per_region: bool = Field(False, description="detect on each region's crop instead of the whole page")
        unclip_ratio: float = Field(1.5, description="how far the DB boxes are grown around the text kernel "
                                                     "(PaddleOCR's default 1.5)")
        box_thresh: float = Field(0.6, description="minimum mean score of a box")
        thresh: float = Field(0.3, description="binarization threshold of the probability map")
        pad: int = Field(0, description="per_region: pixels around a region's crop")
        mask: bool = Field(False, description="per_region: paint everything outside the region polygon white")

    def __init__(self, model_name: str = "PP-OCRv6_medium_det", device: str = "auto", per_region: bool = False,
                 unclip_ratio: float = 1.5, box_thresh: float = 0.6, thresh: float = 0.3, pad: int = 0,
                 mask: bool = False, weights: dict | None = None):
        o = self.Options(model_name=model_name, device=device, per_region=per_region, unclip_ratio=unclip_ratio,
                         box_thresh=box_thresh, thresh=thresh, pad=pad, mask=mask)
        check(o.model_name, weights)
        self.options, self.weights = o, weights
        self.name, self.device, self.per_region = o.model_name, o.device, o.per_region
        self.kwargs = o.model_dump(exclude={"model_name", "device", "per_region"})
        self.revision: str | None = weights["revision"] if weights else None
        self.detector: PaddleTextDetector | None = None

    def load(self) -> None:
        model_dir, self.revision = resolve(self.name, self.weights)
        self.detector = PaddleTextDetector(self.name, self.device, model_dir=model_dir, **self.kwargs)

    def __call__(self, image: np.ndarray, transcription: Transcription, **params) -> Transcription:
        found = []
        if self.per_region:
            for r in sorted(transcription.regions, key=lambda r: (r.reading_order is None, r.reading_order or 0)):
                found.extend(self.detector.detect(image, r))
        else:
            found = self.detector.detect(image)
        transcription.lines = [Line(id=f"det_{i}", region_id=rid or None, reading_order=i, bbox=xywh(BBox.of(pts)),
                                    polygon=pts.tolist(), score=score) for i, (pts, score, rid) in enumerate(found)]
        d = self.detector
        transcription.model.append(ModelInfo(step=self.step, name=self.name, revision=self.revision,
                                             backend="paddlex/onnxruntime",
                                             settings={"unclip_ratio": d.unclip_ratio, "box_thresh": d.box_thresh,
                                                       "thresh": d.thresh, "per_region": self.per_region}))
        return transcription
