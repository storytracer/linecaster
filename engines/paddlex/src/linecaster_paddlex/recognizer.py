"""PP-OCRv6 text recognition through PaddleX's ONNX Runtime engine: PaddleOCR's own recognisers (tiny, small,
medium) on the lines of a transcription.

Lines are cut out the way PaddleX's OCR pipeline cuts them (the minimum-area rectangle of the line
polygon, rotated upright: ``CropByPolys``), sorted by aspect ratio and recognised ``batch_size`` at a
time, as PaddleX's pipeline does. Words: the text split at whitespace (kraken's rule), each word placed
along the line rectangle by the CTC columns of its characters, the same mapping as PaddleX's
``cal_ocr_word_box`` (whose own word list groups punctuation separately)."""
from __future__ import annotations

from typing import ClassVar

import numpy as np
import regex
from pydantic import BaseModel, ConfigDict, Field

from linecaster.geometry import BBox, xywh
from linecaster.transcription import ModelInfo, Transcription, Word

from .compat import create_predictor, paddle_image
from .weights import check, resolve

RECOGNIZERS = ("PP-OCRv6_medium_rec", "PP-OCRv6_small_rec", "PP-OCRv6_tiny_rec")


def line_rectangle(polygon) -> np.ndarray:
    """The minimum-area rectangle of ``polygon`` as top-left, top-right, bottom-right, bottom-left
    (``CropByPolys.get_minarea_rect_crop``'s corner order)."""
    import cv2

    rect = cv2.minAreaRect(np.asarray(polygon, dtype=np.float32).reshape(-1, 2).astype(np.int32))
    p = sorted(cv2.boxPoints(rect).tolist(), key=lambda q: q[0])
    a, d = (p[0], p[1]) if p[1][1] > p[0][1] else (p[1], p[0])
    b, c = (p[2], p[3]) if p[3][1] > p[2][1] else (p[3], p[2])
    return np.array([a, b, c, d], dtype=np.float32)


def crop_line(image: np.ndarray, box: np.ndarray) -> np.ndarray:
    """``CropByPolys.get_rotate_crop_image``: the rectangle warped upright, turned when it stands on end."""
    import cv2

    w = int(max(np.linalg.norm(box[0] - box[1]), np.linalg.norm(box[2] - box[3])))
    h = int(max(np.linalg.norm(box[0] - box[3]), np.linalg.norm(box[1] - box[2])))
    if w == 0 or h == 0:
        return np.zeros((0, 0, 3), dtype=image.dtype)
    m = cv2.getPerspectiveTransform(box, np.float32([[0, 0], [w, 0], [w, h], [0, h]]))
    crop = cv2.warpPerspective(image, m, (w, h), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_CUBIC)
    if crop.shape[0] / crop.shape[1] >= 1.5:
        crop = np.rot90(crop)
    return crop


def line_words(text: str, word_info, box: np.ndarray, line_id: str) -> list[Word]:
    """Words of ``text`` placed along ``box`` by the CTC columns of their characters. ``word_info`` is
    the recogniser's ``[col_num, word_list, word_col_list, state_list]``; flattened, ``word_col_list``
    has one column per character of ``text``."""
    col_num, _, word_cols, _ = word_info
    cols = [c for group in word_cols for c in group]
    if not cols or len(cols) != len(text) or not col_num:
        return []
    a, b, c, d = box

    def at(t: float) -> list[np.ndarray]:
        return [a + (b - a) * t, d + (c - d) * t]

    words, offset = [], 0
    for segment in regex.split(r"(\s+)", text):
        if not segment:
            continue
        if not segment.isspace():
            t0 = min(cols[offset] / col_num, 1.0)
            t1 = min((cols[offset + len(segment) - 1] + 1) / col_num, 1.0)
            pts = np.array(at(t0) + at(t1))
            words.append(Word(id=f"{line_id}_w{len(words)}", text=segment, bbox=[float(v) for v in xywh(BBox.of(pts))]))
        offset += len(segment)
    return words


class PaddleRecognitionModel:
    """linecaster engine model for the recognition step: a PaddleOCR text recogniser on every line of the
    transcription (``RECOGNIZERS``). Fills text, confidence (the recogniser's mean character probability) and words
    (positions only; PaddleX gives no per-word confidence). A page's result depends only on the page. The model
    files: ``weights`` (a catalogue pin) or the catalogue's newest pin for ``model_name`` (``weights.resolve``)."""

    engine_id: ClassVar[str] = "paddlex.recognition.v1"
    step = "recognition"
    capabilities: ClassVar[dict] = {"unit": "line", "produces": ["text", "words", "line_confidences"]}

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid", protected_namespaces=())

        model_name: str = Field("PP-OCRv6_medium_rec", description="PaddleX text recogniser: "
                                                                   "PP-OCRv6_{tiny,small,medium}_rec")
        device: str = Field("auto", description="auto, cpu, cuda, tensorrt or coreml (ONNX Runtime providers)")
        batch_size: int = Field(8, description="line images per forward pass (sorted by aspect ratio first, as "
                                               "PaddleX's pipeline does)")
        words: bool = Field(True, description="word boxes from the CTC columns (PaddleX's return_word_box)")

    def __init__(self, model_name: str = "PP-OCRv6_medium_rec", device: str = "auto", batch_size: int = 8,
                 words: bool = True, weights: dict | None = None):
        o = self.Options(model_name=model_name, device=device, batch_size=batch_size, words=words)
        check(o.model_name, weights)
        self.options, self.weights = o, weights
        self.name, self.device, self.batch_size, self.words = o.model_name, o.device, o.batch_size, o.words
        self.revision: str | None = weights["revision"] if weights else None
        self.predictor = None

    def load(self) -> None:
        model_dir, self.revision = resolve(self.name, self.weights)
        self.predictor = create_predictor(self.name, self.device, batch_size=max(int(self.batch_size), 1),
                                          model_dir=model_dir)

    def __call__(self, image: np.ndarray, transcription: Transcription, **params) -> Transcription:
        lines = [ln for ln in transcription.lines if ln.polygon or ln.bbox]
        boxes, crops = [], []
        for ln in lines:
            x, y, w, h = ln.bbox if not ln.polygon else (0, 0, 0, 0)
            poly = ln.polygon or BBox(x, y, x + w, y + h).polygon.tolist()
            box = line_rectangle(poly)
            boxes.append(box)
            crops.append(paddle_image(crop_line(image, box)))
        keep = [i for i, cr in enumerate(crops) if cr.size]
        # PaddleX's pipeline order: narrowest first, so each batch pads as little as possible
        order = sorted(keep, key=lambda i: crops[i].shape[1] / float(crops[i].shape[0]))
        results = {}
        if order:
            for i, res in zip(order, self.predictor.predict([crops[i] for i in order], return_word_box=self.words)):
                results[i] = res
        for i, ln in enumerate(lines):
            res = results.get(i)
            if res is None:
                ln.text, ln.confidence, ln.words = "", 0.0, []
                continue
            rec = res["rec_text"]
            text, info = (rec[0], rec[1]) if isinstance(rec, tuple) else (rec, None)
            ln.text, ln.confidence = text, float(res["rec_score"])
            ln.words = line_words(text, info, boxes[i], ln.id) if info is not None else []
        transcription.model.append(ModelInfo(step=self.step, name=self.name, revision=self.revision,
                                             backend="paddlex/onnxruntime",
                                             settings={"batch_size": self.batch_size, "words": self.words}))
        return transcription
