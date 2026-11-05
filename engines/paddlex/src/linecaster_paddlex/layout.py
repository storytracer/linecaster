"""Layout analysis with PaddleX's PP-DocLayout models.

``PP-DocLayoutV3`` (default) predicts region polygons and the reading order itself; PaddleX hands
its boxes back already sorted by that order. ``PP-DocLayout_plus-L`` (PP-StructureV3's layout
model) only gives boxes, so its regions are ordered with our XY-cut.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from linecaster.data import ModelInfo, Region as LCRegion, Transcription
from linecaster.data.geometry import BBox, xywh
from linecaster.data.geometry.order import suppress_contained, xy_cut_order

from .compat import create_predictor, paddle_image
from .weights import check, resolve


@dataclass
class Region:
    """A layout region while the model's output is post-processed (polygon as an array)."""

    label: str
    polygon: np.ndarray
    score: float = 1.0
    order: int | None = None
    id: str = ""
    raw_label: str = ""

    @property
    def bbox(self) -> BBox:
        return BBox.of(self.polygon)

#: PP-DocLayout labels -> Docling labels. ``number`` is a page number and is placed by position.
LABEL_MAP = {
    "doc_title": "title",
    "paragraph_title": "section_header",
    "text": "text",
    "vertical_text": "text",
    "abstract": "text",
    "content": "text",
    "aside_text": "text",
    "algorithm": "code",
    "reference": "reference",
    "reference_content": "reference",
    "footnote": "footnote",
    "vision_footnote": "footnote",
    "header": "page_header",
    "footer": "page_footer",
    "figure_title": "caption",
    "table_title": "caption",
    "chart_title": "caption",
    "formula": "formula",
    "display_formula": "formula",
    "inline_formula": "formula",
    "formula_number": "text",
    "table": "table",
    "image": "picture",
    "chart": "picture",
    "header_image": "picture",
    "footer_image": "picture",
    "seal": "seal",
}

#: PaddleX's own post-processing for each model (class index -> value): PP-StructureV3's per-class
#: score thresholds for PP-DocLayout_plus-L, PaddleOCR-VL-1.5's uniform threshold and per-class
#: box-merge modes for PP-DocLayoutV3 (``large`` keeps the enclosing box for chart, display and
#: inline formula, doc and paragraph title; ``union`` elsewhere).
PLUS_L_THRESHOLDS = {0: 0.3, 1: 0.5, 2: 0.4, 3: 0.5, 4: 0.5, 5: 0.5, 6: 0.5, 7: 0.3, 8: 0.5, 9: 0.5, 10: 0.5, 11: 0.5,
                     12: 0.5, 13: 0.5, 14: 0.5, 15: 0.45, 16: 0.5, 17: 0.5, 18: 0.5, 19: 0.5}
V3_MERGE_MODES = {i: ("large" if i in (3, 5, 6, 15, 17) else "union") for i in range(25)}
MODEL_DEFAULTS = {
    "PP-DocLayoutV3": {"threshold": 0.3, "merge_mode": V3_MERGE_MODES},
    "PP-DocLayout_plus-L": {"threshold": PLUS_L_THRESHOLDS, "merge_mode": "large"},
}
THRESHOLDS = PLUS_L_THRESHOLDS   # backwards-compatible name


def regions_from_boxes(boxes, page_height: float, header_zone: float = 0.15) -> tuple[list[Region], bool]:
    """Turn PaddleX layout boxes into ``Region``s with Docling labels.

    Returns the regions and whether the model ordered them: a model with learned reading order
    (PP-DocLayoutV3) returns an ``order`` field on every box and PaddleX sorts the boxes by it, so
    the list position is the reading order and is stored in ``Region.order``. Boxes without that
    field are returned with ``order=None``. Polygons come from ``polygon_points`` when the model
    gives them, else from the rectangle.
    """
    learned = len(boxes) > 0 and all("order" in b for b in boxes)
    regions = []
    for i, box in enumerate(boxes):
        x0, y0, x1, y1 = (float(v) for v in box["coordinate"])
        raw = str(box["label"])
        label = LABEL_MAP.get(raw, "text")
        if raw == "number":
            label = "page_header" if (y0 + y1) / 2 < header_zone * page_height else "page_footer"
        poly = box.get("polygon_points")
        polygon = np.asarray(poly, dtype=float) if poly is not None and len(poly) >= 3 else BBox(x0, y0, x1, y1).polygon
        regions.append(Region(label, polygon, float(box["score"]), i if learned else None, f"{raw}_{i}", raw_label=raw))
    return regions, learned


class PaddleLayout:
    """PP-DocLayoutV3 (default) region detection with the model's own reading order.

    Any PaddleX layout-detection model name works; models without learned order get XY-cut order.
    ``threshold`` and ``merge_mode`` default to PaddleX's own settings for the two known models.
    """

    def __init__(self, model_name: str = "PP-DocLayoutV3", device: str = "auto",
                 threshold: float | dict[int, float] | None = None,
                 header_zone: float = 0.15, nms: bool = True, merge_mode: str | dict[int, str] | None = None,
                 max_containment: float = 0.8, model_dir: str | None = None):
        defaults = MODEL_DEFAULTS.get(model_name, {"threshold": 0.5, "merge_mode": "large"})
        self.model_name, self.header_zone = model_name, header_zone
        self.threshold = defaults["threshold"] if threshold is None else threshold
        self.merge_mode = defaults["merge_mode"] if merge_mode is None else merge_mode
        self.nms, self.max_containment = nms, max_containment
        self.predictor = create_predictor(model_name, device, model_dir=model_dir)

    def analyze(self, image: np.ndarray) -> list[Region]:
        res = next(iter(self.predictor.predict(paddle_image(image), threshold=self.threshold,
                                               layout_nms=self.nms, layout_merge_bboxes_mode=self.merge_mode)))
        regions, learned = regions_from_boxes(res["boxes"], image.shape[0], self.header_zone)
        regions = suppress_contained(regions, self.max_containment)
        if learned:
            regions.sort(key=lambda r: r.order)
            for rank, r in enumerate(regions):
                r.order = rank
        else:
            for rank, i in enumerate(xy_cut_order([r.bbox for r in regions])):
                regions[i].order = rank
        return regions


class PaddleLayoutModel:
    """linecaster engine model for the layout step: fills ``Transcription.regions`` (Docling labels,
    the model's reading order, PP-DocLayoutV3's polygons). Replaces any regions already present.
    The model files: ``weights`` (a catalogue pin) or the catalogue's newest pin for ``model_name``
    (``weights.resolve``)."""

    engine_id: ClassVar[str] = "paddlex.layout.v1"
    step = "layout"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["regions", "reading_order"]}

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid", protected_namespaces=())

        model_name: str = Field("PP-DocLayoutV3", description="PaddleX layout model (PP-DocLayoutV3: learned "
                                                              "reading order and polygons; others: XY-cut order)")
        device: str = Field("auto", description="auto, cpu, cuda, tensorrt or coreml (ONNX Runtime providers)")
        threshold: float | dict[int, float] | None = Field(
            None, description="score threshold, one or per class index; None: PaddleX's own for the model "
                              "(PP-DocLayoutV3 0.3, PP-DocLayout_plus-L PP-StructureV3's per class)")
        header_zone: float = Field(0.15, description="share of the page height from the top in which a page "
                                                     "number is a page header (below: a page footer)")
        nms: bool = Field(True, description="PaddleX's layout NMS")
        merge_mode: str | dict[int, str] | None = Field(
            None, description="PaddleX's box merge mode (large, union, small), one or per class index; None: "
                              "PaddleX's own for the model")
        max_containment: float = Field(0.8, description="a region contained in another by more than this share "
                                                        "of its area is dropped")

    def __init__(self, model_name: str = "PP-DocLayoutV3", device: str = "auto",
                 threshold: float | dict[int, float] | None = None, header_zone: float = 0.15, nms: bool = True,
                 merge_mode: str | dict[int, str] | None = None, max_containment: float = 0.8,
                 weights: dict | None = None):
        o = self.Options(model_name=model_name, device=device, threshold=threshold, header_zone=header_zone, nms=nms,
                         merge_mode=merge_mode, max_containment=max_containment)
        check(o.model_name, weights)
        self.options, self.weights = o, weights
        self.name, self.device = o.model_name, o.device
        self.kwargs = o.model_dump(exclude={"model_name", "device"})
        self.revision: str | None = weights["revision"] if weights else None
        self.layout: PaddleLayout | None = None

    def load(self) -> None:
        model_dir, self.revision = resolve(self.name, self.weights)
        self.layout = PaddleLayout(self.name, self.device, model_dir=model_dir, **self.kwargs)

    def __call__(self, image: np.ndarray, transcription: Transcription, **params) -> Transcription:
        regions = self.layout.analyze(image)
        transcription.regions = [
            LCRegion(id=r.id, label=r.label, raw_label=r.raw_label, polygon=np.asarray(r.polygon, dtype=float).tolist(),
                     bbox=xywh(r.bbox), score=r.score, reading_order=r.order) for r in regions]
        transcription.model.append(ModelInfo(step=self.step, name=self.name, revision=self.revision,
                                             backend="paddlex/onnxruntime",
                                             settings={"threshold": str(self.layout.threshold) if isinstance(self.layout.threshold, float) else "model default",
                                                       "header_zone": self.layout.header_zone, "nms": self.layout.nms}))
        return transcription
