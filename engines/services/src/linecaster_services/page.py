"""What every page engine of this package shares: the page image encoded as the vendor's client sends it, and the
service's answer as a text-only transcription."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

from linecaster.data import Annotator, RawOutput, Source, Transcription


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


def text_source(given: Transcription | None) -> Source:
    """The source of a page engine's transcription: the one it was given (its image), produced, as text."""
    source = given.source.model_copy(deep=True) if given is not None else Source(kind="produced")
    if source.format is None:
        source.format = "text"
    return source


def text_transcription(raw: str, annotator: Annotator, completion_tokens: int | None = None,
                       given: Transcription | None = None, **extensions) -> Transcription:
    """A text-only transcription of ``raw`` by ``annotator``, made anew for the transcription it was ``given``
    (whose source it keeps, ``text_source``): ``raw`` verbatim as its raw output (with ``completion_tokens``), one line
    per text line, no geometry, each read as it is (the transcription's text equals ``raw``); ``extensions``
    (namespaced, ``<engine>__<field>``) on the transcription."""
    t = Transcription(source=text_source(given), **extensions)
    a = t.add_annotator(annotator)
    o = t.add_output(RawOutput(annotator=a, content=raw, completion_tokens=completion_tokens))
    ids = []
    for i, text in enumerate(raw.split("\n")):
        line = t.add_line(a, f"l{i}", output=o)
        t.read(a, line, text, output=o)
        ids.append(line.id)
    t.add_order(a, lines=ids)
    return t
