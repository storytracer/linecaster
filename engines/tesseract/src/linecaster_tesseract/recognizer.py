"""Tesseract's LSTM recogniser on the lines of a transcription, one line image at a time.

Each line is cut out as the bounding box of its polygon, with ``pad`` pixels around it and everything
outside the polygon painted white, and read with page segmentation mode 7 (one line of text), so
Tesseract reads the lines a line detector found instead of segmenting the page itself. Words and
their boxes come from Tesseract (``RIL.WORD``), moved back into page coordinates; confidences are
Tesseract's, scaled to 0–1.
"""
from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from linecaster.data import ModelInfo, Transcription, Word
from linecaster.data.geometry import BBox, xywh

from .models import MODEL_IDS, Tessdata, tessdata, tessdata_dir


def crop_line(image: np.ndarray, polygon, pad: int) -> tuple[np.ndarray, int, int]:
    from PIL import ImageDraw

    poly = np.asarray(polygon, dtype=float).reshape(-1, 2)
    b = BBox.of(poly)
    h, w = image.shape[:2]
    c = BBox(b.x0 - pad, b.y0 - pad, b.x1 + pad, b.y1 + pad).clipped(w, h)
    x0, y0, x1, y1 = int(c.x0), int(c.y0), int(np.ceil(c.x1)), int(np.ceil(c.y1))
    crop = image[y0:y1, x0:x1].copy()
    if crop.size and len(poly) >= 3:
        mask = Image.new("L", (crop.shape[1], crop.shape[0]), 0)
        ImageDraw.Draw(mask).polygon([(float(x - x0), float(y - y0)) for x, y in poly], fill=1)
        crop[np.asarray(mask) == 0] = 255
    return crop, x0, y0


class TesseractRecognitionEngine:
    """linecaster engine model for the recognition step: Tesseract 5 (LSTM) on every line of the
    transcription. ``lang`` is a tessdata language or script (``eng``, ``deu+lat``, ``script/Latin``),
    ``data`` ``best`` or ``fast``. Fills text, confidence and words with boxes and confidences.
    The language data: ``weights`` (a catalogue pin; only its files) or ``data``'s newest pin in the catalogue."""

    engine_id: ClassVar[str] = "tesseract.recognition.v1"
    step = "recognition"
    capabilities: ClassVar[dict] = {"unit": "line",
                                    "produces": ["text", "words", "word_confidences", "line_confidences"]}

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        lang: str = Field("eng", description="tessdata language or script, + for several: eng, deu+lat, "
                                             "script/Latin")
        data: Literal["best", "fast"] = Field("best", description="tessdata_best (float LSTM, most accurate) or "
                                                                  "tessdata_fast (integer, faster); with weights, "
                                                                  "the data set the pin belongs to")
        pad: int = Field(4, description="white pixels around each line image")
        dpi: int = Field(300, description="the resolution Tesseract assumes (user_defined_dpi)")

    def __init__(self, lang: str = "eng", data: str = "best", pad: int = 4, dpi: int = 300,
                 weights: dict | None = None):
        o = self.Options(lang=lang, data=data, pad=pad, dpi=dpi)
        if weights is not None and weights["model"] != MODEL_IDS[o.data]:
            raise ValueError(f"data={o.data!r} does not name the pinned weights {weights['model']!r}")
        self.options, self.weights = o, weights
        self.lang, self.data, self.pad, self.dpi = o.lang, o.data, o.pad, o.dpi
        self.name = f"tesseract {o.data}/{o.lang}"
        self.revision: str | None = weights["revision"] if weights else None
        self.api = None

    def load(self) -> None:
        import tesserocr

        td = Tessdata.of(self.weights) if self.weights is not None else tessdata(self.data)
        self.revision = td.commit
        path = tessdata_dir(self.lang, self.data, td=td, strict=self.weights is not None)
        self.api = tesserocr.PyTessBaseAPI(path=str(path), lang=self.lang, psm=tesserocr.PSM.SINGLE_LINE,
                                           oem=tesserocr.OEM.LSTM_ONLY)
        self.api.SetVariable("user_defined_dpi", str(self.dpi))
        self.version = tesserocr.tesseract_version().split()[1]

    def read(self, crop: np.ndarray, dx: int, dy: int, line_id: str) -> list[Word]:
        from tesserocr import RIL, iterate_level

        self.api.SetImage(Image.fromarray(crop))
        self.api.Recognize()
        words = []
        it = self.api.GetIterator()
        if it is None:
            return words
        for w in iterate_level(it, RIL.WORD):
            try:
                text = (w.GetUTF8Text(RIL.WORD) or "").strip()
            except RuntimeError:   # tesserocr's "No text returned": an empty line image
                continue
            if not text:
                continue
            x0, y0, x1, y1 = w.BoundingBox(RIL.WORD)
            words.append(Word(id=f"{line_id}_w{len(words)}", text=text,
                              bbox=[float(v) for v in xywh(BBox(x0 + dx, y0 + dy, x1 + dx, y1 + dy))],
                              confidence=float(w.Confidence(RIL.WORD)) / 100.0))
        return words

    def __call__(self, image: np.ndarray, transcription: Transcription, **params) -> Transcription:
        for ln in transcription.lines:
            poly = ln.polygon
            if not poly and ln.bbox:
                x, y, w, h = ln.bbox
                poly = BBox(x, y, x + w, y + h).polygon.tolist()
            crop, dx, dy = crop_line(image, poly, self.pad) if poly else (np.zeros((0, 0)), 0, 0)
            words = self.read(crop, dx, dy, ln.id) if crop.size else []
            ln.words = words
            ln.text = " ".join(w.text for w in words)
            ln.confidence = float(np.mean([w.confidence for w in words])) if words else 0.0
        transcription.model.append(ModelInfo(step=self.step, name=self.name, revision=self.revision,
                                             backend=f"tesseract {self.version} (tesserocr)",
                                             settings={"lang": self.lang, "data": self.data, "psm": 7,
                                                       "pad": self.pad, "dpi": self.dpi}))
        return transcription
