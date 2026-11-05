"""Axis-aligned boxes in page pixels (origin top-left) for the geometry the blocks compute.

The data model stores ``[x, y, width, height]``; algorithms work on ``BBox`` (corners) derived from a
shape's polygon, so the arithmetic is the same as in the producing engine (``BBox.of(polygon)``)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float

    @classmethod
    def of(cls, polygon: np.ndarray) -> "BBox":
        p = np.asarray(polygon, dtype=float).reshape(-1, 2)
        return cls(float(p[:, 0].min()), float(p[:, 1].min()), float(p[:, 0].max()), float(p[:, 1].max()))

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def polygon(self) -> np.ndarray:
        return np.array([[self.x0, self.y0], [self.x1, self.y0], [self.x1, self.y1], [self.x0, self.y1]], dtype=float)

    def intersection_area(self, other: "BBox") -> float:
        w = min(self.x1, other.x1) - max(self.x0, other.x0)
        h = min(self.y1, other.y1) - max(self.y0, other.y0)
        return max(w, 0.0) * max(h, 0.0)

    def clipped(self, width: float, height: float) -> "BBox":
        return BBox(max(self.x0, 0.0), max(self.y0, 0.0), min(self.x1, width), min(self.y1, height))


def xywh(b: BBox) -> list[float]:
    """``[x, y, width, height]`` of a box, as the data model stores it."""
    return [b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0]


def bbox_of(points) -> BBox:
    """The bounding box of a polygon (any sequence of ``[x, y]``)."""
    return BBox.of(np.asarray(points, dtype=float))
