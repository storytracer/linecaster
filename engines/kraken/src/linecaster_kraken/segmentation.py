"""Bridge from linecaster's lines to kraken's containers.

kraken's recognizer takes a ``Segmentation`` of line records. This builds one from linecaster
``Line``s: a ``BaselineLine`` (boundary polygon + baseline) when the line step gave a baseline, else a
``BBoxLine`` with the axis-aligned bounds of the polygon. Record ids are the lines' ids
(``<region id>_l<n>``) and each record names its region (``Line.region``, or the region given for it, e.g.
``Transcription.region_of``).
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from linecaster.data import Line
from linecaster.data.geometry import BBox, bbox_of


def clip_points(poly, width: int, height: int) -> list[tuple[int, int]]:
    pts = np.rint(np.asarray(poly, dtype=float)).astype(int)
    pts[:, 0] = np.clip(pts[:, 0], 0, width - 1)
    pts[:, 1] = np.clip(pts[:, 1], 0, height - 1)
    return [(int(x), int(y)) for x, y in pts]


def clip_box(b: BBox, width: int, height: int) -> tuple[int, int, int, int]:
    (x0, y0), (x1, y1) = clip_points(np.array([[b.x0, b.y0], [b.x1, b.y1]]), width, height)
    return x0, y0, x1, y1


def line_record(ln: Line, width: int, height: int, text_direction: str = "horizontal-lr",
                region: str | None = None):
    """A kraken ``BaselineLine`` or ``BBoxLine`` for one ``Line``, in ``region`` (default: ``ln.region``)."""
    from kraken.containers import BaselineLine, BBoxLine

    region = region if region is not None else ln.region
    regions = [region] if region else None
    if ln.baseline is not None:
        return BaselineLine(id=ln.id, baseline=clip_points(ln.baseline, width, height),
                            boundary=clip_points(ln.polygon, width, height), regions=regions)
    box = bbox_of(ln.polygon) if ln.polygon else BBox(ln.box[0], ln.box[1], ln.box[0] + ln.box[2], ln.box[1] + ln.box[3])
    return BBoxLine(id=ln.id, bbox=clip_box(box, width, height), regions=regions, text_direction=text_direction)


def lines_to_segmentation(width: int, height: int, lines: Sequence[Line], text_direction: str = "horizontal-lr",
                          imagename: str = "", regions: Sequence[str | None] | None = None):
    """A kraken ``Segmentation`` of ``lines`` in the given order; ``regions``: each line's region (default: its
    ``region``)."""
    from kraken.containers import Segmentation

    regions = list(regions) if regions is not None else [None] * len(lines)
    records = [line_record(ln, width, height, text_direction, region) for ln, region in zip(lines, regions)]
    seg_type = "baselines" if any(r.type == "baselines" for r in records) else "bbox"
    return Segmentation(type=seg_type, imagename=imagename, text_direction=text_direction,
                        script_detection=False, lines=records)
