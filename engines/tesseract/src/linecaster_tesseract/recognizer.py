"""Tesseract's LSTM recognizer on the lines of a transcription, one line image at a time.

Each line is cut out as the bounding box of its polygon, with ``pad`` pixels around it and everything
outside the polygon painted white, and read with page segmentation mode 7 (one line of text), so
Tesseract reads the lines a line detector found instead of segmenting the page itself; a line whose recorded writing
direction is vertical (``Transcription.direction``: ``vertical-rl``, ``vertical-lr``) with mode 5 (a block of
vertical text), for tessdata's vertical models (``script/HanT_vert``, ``script/Japanese_vert``). The line's text is
Tesseract's own (in logical order, spaced as Tesseract spaces it: no spaces between the letters of scripts written
without them, right-to-left words in reading order); words and their boxes come from Tesseract (``RIL.WORD``), moved
back into page coordinates and grouped as the words of the line's text where Tesseract's differ (``as_text_words``);
confidences are Tesseract's, scaled to 0–1.
"""
from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from linecaster.data import Annotator, Transcription, Word
from linecaster.data.geometry import BBox, xywh

from linecaster_tesseract.models import MODEL_IDS, Tessdata, tessdata, tessdata_dir


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


def as_text_words(words: list[Word], text: str) -> list[Word]:
    """Tesseract's words of a line as the words of its line text: where they differ (a right-to-left word's letters
    in visual order, Thai or Chinese letters as words of their own), consecutive words are grouped by their number of
    characters into each of the text's words, which takes their joined box and their mean confidence; words that
    cannot be grouped so stay Tesseract's."""
    tokens = text.split()
    if [w.text for w in words] == tokens:
        return words
    out, k = [], 0
    for token in tokens:
        group, n = [], 0
        while k < len(words) and n < len(token):
            group.append(words[k])
            n += len(words[k].text)
            k += 1
        if n != len(token):
            return words
        boxes = [BBox(x, y, x + w, y + h) for x, y, w, h in (g.box for g in group)]
        box = BBox(min(b.x0 for b in boxes), min(b.y0 for b in boxes), max(b.x1 for b in boxes),
                   max(b.y1 for b in boxes))
        out.append(Word(text=token, box=[float(v) for v in xywh(box)],
                        confidence=float(np.mean([g.confidence for g in group]))))
    return out if k == len(words) else words


class TesseractRecognitionEngine:
    """linecaster engine for the recognition step: Tesseract 5 (LSTM) on every line of the
    transcription that has no reading yet. ``lang`` is a tessdata language or script (``eng``, ``deu+lat``,
    ``script/Latin``), ``data`` ``best`` or ``fast``. Gives each line its reading: text, confidence and words with
    boxes and confidences.
    The language data: ``weights`` (a catalog pin; only its files) or ``data``'s newest pin in the catalog."""

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
        preserve_interword_spaces: bool = Field(
            False, description="Tesseract's preserve_interword_spaces: no space between letters Tesseract reads as "
                               "words of their own (Thai, Chinese, Japanese, Korean); for scripts written with "
                               "spaces it can drop one")

    def __init__(self, lang: str = "eng", data: str = "best", pad: int = 4, dpi: int = 300,
                 preserve_interword_spaces: bool = False, weights: dict | None = None):
        o = self.Options(lang=lang, data=data, pad=pad, dpi=dpi, preserve_interword_spaces=preserve_interword_spaces)
        if weights is not None and weights["model"] != MODEL_IDS[o.data]:
            raise ValueError(f"data={o.data!r} does not name the pinned weights {weights['model']!r}")
        self.options, self.weights = o, weights
        self.lang, self.data, self.pad, self.dpi = o.lang, o.data, o.pad, o.dpi
        self.preserve_interword_spaces = o.preserve_interword_spaces
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
        if self.preserve_interword_spaces:
            self.api.SetVariable("preserve_interword_spaces", "1")
        self.version = tesserocr.tesseract_version().split()[1]

    def read(self, crop: np.ndarray, dx: int, dy: int, vertical: bool = False) -> list[Word]:
        """The words of a line image (``crop``, at ``dx``, ``dy`` on the page), read as one line of text or, with
        ``vertical``, as a block of vertical text; the line's text is ``text()`` afterwards."""
        from tesserocr import PSM, RIL, iterate_level

        self.api.SetPageSegMode(PSM.SINGLE_BLOCK_VERT_TEXT if vertical else PSM.SINGLE_LINE)
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
            words.append(Word(text=text,
                              box=[float(v) for v in xywh(BBox(x0 + dx, y0 + dy, x1 + dx, y1 + dy))],
                              confidence=float(w.Confidence(RIL.WORD)) / 100.0))
        return words

    def text(self) -> str:
        """The text of the line read last, as Tesseract writes it (its lines joined by a space)."""
        try:
            return " ".join((self.api.GetUTF8Text() or "").split("\n")).strip()
        except RuntimeError:       # tesserocr's "No text returned": an empty line image
            return ""

    def __call__(self, image: np.ndarray, transcription: Transcription, **params) -> Transcription:
        t = transcription
        vertical = {ln.id for ln in t.lines if ln.reading is None
                    and (t.direction(ln.id) or "").startswith("vertical")}
        settings = {"lang": self.lang, "data": self.data, "psm": 7, "pad": self.pad, "dpi": self.dpi}
        if vertical:
            settings["psm_vertical"] = 5
        if self.preserve_interword_spaces:
            settings["preserve_interword_spaces"] = True
        a = t.add_annotator(Annotator(step=self.step, name=self.name, revision=self.revision,
                                      backend=f"tesseract {self.version} (tesserocr)", settings=settings))
        for ln in t.lines:
            if ln.reading is not None:
                continue
            poly = ln.polygon
            if not poly and ln.box:
                x, y, w, h = ln.box
                poly = BBox(x, y, x + w, y + h).polygon.tolist()
            crop, dx, dy = crop_line(image, poly, self.pad) if poly else (np.zeros((0, 0)), 0, 0)
            words = self.read(crop, dx, dy, ln.id in vertical) if crop.size else []
            text = self.text() if crop.size else ""
            words = as_text_words(words, text)
            t.read(a, ln, text,
                   float(np.mean([w.confidence for w in words])) if words else 0.0, words=words)
        return t
