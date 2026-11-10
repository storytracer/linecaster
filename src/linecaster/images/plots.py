"""Layout plots: a page image with the regions, lines and labels of a transcription drawn in.

Region polygons colored by Docling label with a tag (label, heading level, reading-order rank and
the producing model's own label when it differs), the lines as thin boxes, furniture (page numbers,
running heads) in gray. Large pages are scaled down to ``max_width`` pixels. Pillow only.
"""
from __future__ import annotations

import io

import numpy as np

from ..data.geometry import bbox_of
from ..data.transcription import Transcription
from ..text.typography import line_bbox

COLORS = {
    "text": (30, 100, 230), "section_header": (220, 40, 40), "title": (220, 40, 40),
    "page_header": (120, 120, 120), "page_footer": (120, 120, 120),
    "picture": (150, 60, 200), "table": (240, 140, 20), "caption": (0, 150, 150), "footnote": (0, 150, 150),
    "formula": (200, 120, 0), "list_item": (30, 100, 230),
}
DEFAULT = (200, 170, 0)
ROW = (0, 170, 60)


def plot_layout(image, t: Transcription, max_width: int = 2400, fmt: str = "JPEG", quality: int = 88) -> bytes:
    """The plot of ``t`` on ``image`` (an RGB array or a PIL image), encoded as ``fmt`` (JPEG by default)."""
    from PIL import Image, ImageDraw, ImageFont

    im = (Image.fromarray(image) if isinstance(image, np.ndarray) else image).convert("RGB")
    width, height = im.size
    scale = min(1.0, max_width / max(width, 1))
    if scale < 1.0:
        im = im.resize((int(width * scale), int(height * scale)), Image.LANCZOS)
    d = ImageDraw.Draw(im, "RGBA")
    size = max(12, int(im.width / 90))
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:  # older Pillow
        font = ImageFont.load_default()
    line_w = max(2, im.width // 800)
    by_region: dict[str | None, list] = {}
    for ln in t.lines:
        by_region.setdefault(ln.region_id, []).append(ln)
    for r in t.regions:                        # lines first, regions on top
        for ln in by_region.get(r.id, []):
            b = line_bbox(ln)
            d.rectangle((b.x0 * scale, b.y0 * scale, b.x1 * scale, b.y1 * scale), outline=ROW + (255,),
                        width=max(1, line_w // 2))
    for r in t.regions:
        color = COLORS.get(r.label, DEFAULT)
        pts = [(float(x) * scale, float(y) * scale) for x, y in np.asarray(r.polygon, dtype=float).reshape(-1, 2)]
        if len(pts) >= 3:
            d.polygon(pts, outline=color + (255,), fill=color + (28,))
            d.line(pts + [pts[0]], fill=color + (255,), width=line_w)
        tag = (r.label + (f" h{r.heading_level}" if r.heading_level else "")
               + (f" #{r.reading_order}" if r.reading_order is not None else ""))
        if r.raw_label and r.raw_label.split("/")[-1] not in ("", r.label):
            tag += f" ({r.raw_label.split('/')[-1]})"
        b = bbox_of(r.polygon)
        x, y = b.x0 * scale, b.y0 * scale
        tw = d.textlength(tag, font=font) + 8
        d.rectangle((x, y - size - 6, x + tw, y), fill=color + (230,))
        d.text((x + 4, y - size - 4), tag, fill=(255, 255, 255, 255), font=font)
    out = io.BytesIO()
    if fmt.upper() in ("JPEG", "JPG"):
        im.save(out, "JPEG", quality=quality)
    else:
        im.save(out, fmt)
    return out.getvalue()
