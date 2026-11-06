"""What every page engine of this package shares: the page image encoded as the vendor's client sends it, and the
service's answer as a text-only transcription."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

from linecaster.data import Line, Source, StepInfo, Transcription


def rgb(image: np.ndarray) -> Image.Image:
    """The page image (an RGB array) as a Pillow image."""
    return Image.fromarray(np.asarray(image, dtype=np.uint8)).convert("RGB")


def jpeg(img: Image.Image, longest_edge: int | None, quality: int) -> bytes:
    """``img`` scaled down (LANCZOS) so its longest side is at most ``longest_edge`` (never up), as JPEG."""
    w, h = img.size
    if longest_edge and max(w, h) > longest_edge:
        scale = longest_edge / max(w, h)
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def png(img: Image.Image) -> bytes:
    """``img`` as a lossless PNG, at its own size."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def text_transcription(raw: str, step: StepInfo, **extra) -> Transcription:
    """A text-only transcription of ``raw``: one line per text line, no geometry; ``raw`` kept verbatim in
    ``extra["raw"]`` (the transcription's text equals it), with ``extra`` next to it."""
    lines = [Line(id=f"l{i}", reading_order=i, text=t) for i, t in enumerate(raw.split("\n"))]
    return Transcription(lines=lines, steps=[step], source=Source(kind="produced", format="text"),
                         extra={"raw": raw, **extra})
