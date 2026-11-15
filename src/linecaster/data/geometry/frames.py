"""Writing directions as frames: boxes moved so that any direction reads as left to right, top to bottom.

The ordering algorithms (rows of lines, XY-cut, XY-Cut++, slotting unordered regions, a recomposition's margins)
were written for horizontal text read left to right. ``to_frame`` maps a box into the frame of a writing direction
(``linecaster.data.writing.DIRECTIONS``) where that holds, ``from_frame`` maps it back:

* ``horizontal-lr``: as it is;
* ``horizontal-rl``: mirrored (x negated): the rightmost box comes first along a row;
* ``vertical-rl``: rotated: a column becomes a row (y becomes x) and columns stack from the right (x negated
  becomes y), so the rightmost column is read first, each top to bottom;
* ``vertical-lr``: the axes swapped: columns from the left, each top to bottom.

Only the order of boxes is meaningful in a frame (coordinates may be negative); no page size is needed.
"""
from __future__ import annotations

from typing import Sequence

from .types import BBox

HORIZONTAL_LR = "horizontal-lr"


def to_frame(b: BBox, direction: str | None) -> BBox:
    """``b`` in the frame of ``direction`` (``None``: ``horizontal-lr``)."""
    if direction in (None, HORIZONTAL_LR):
        return b
    if direction == "horizontal-rl":
        return BBox(-b.x1, b.y0, -b.x0, b.y1)
    if direction == "vertical-rl":
        return BBox(b.y0, -b.x1, b.y1, -b.x0)
    if direction == "vertical-lr":
        return BBox(b.y0, b.x0, b.y1, b.x1)
    raise ValueError(f"unknown writing direction {direction!r}")


def from_frame(b: BBox, direction: str | None) -> BBox:
    """``to_frame``'s inverse."""
    if direction in (None, HORIZONTAL_LR):
        return b
    if direction == "horizontal-rl":
        return BBox(-b.x1, b.y0, -b.x0, b.y1)
    if direction == "vertical-rl":
        return BBox(-b.y1, b.x0, -b.y0, b.x1)
    if direction == "vertical-lr":
        return BBox(b.y0, b.x0, b.y1, b.x1)
    raise ValueError(f"unknown writing direction {direction!r}")


def boxes_in_frame(boxes: Sequence[BBox], direction: str | None) -> list[BBox]:
    return [to_frame(b, direction) for b in boxes]


class Framed:
    """An object with a ``bbox`` seen in a direction's frame: ``bbox`` transformed, every other attribute (an
    ``order`` an algorithm sets, a label it reads) passed through to the object itself."""

    __slots__ = ("_obj", "bbox")

    def __init__(self, obj, direction: str | None):
        object.__setattr__(self, "_obj", obj)
        object.__setattr__(self, "bbox", to_frame(obj.bbox, direction))

    def __getattr__(self, name):
        return getattr(self._obj, name)

    def __setattr__(self, name, value):
        setattr(self._obj, name, value)


def framed(objs: Sequence, direction: str | None) -> list:
    """``objs`` seen in the frame of ``direction`` (the objects themselves for ``horizontal-lr``)."""
    if direction in (None, HORIZONTAL_LR):
        return list(objs)
    return [Framed(o, direction) for o in objs]


__all__ = ["HORIZONTAL_LR", "Framed", "boxes_in_frame", "framed", "from_frame", "to_frame"]
