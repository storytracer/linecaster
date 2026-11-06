"""Indra OCR on a whole page, through the ``indra-ocr`` package's own image path.

The engine takes the page image's file bytes, as the reader brought them (``image_input = "bytes"``): they are
written to a temporary file with their format's suffix and read with ``Converter.convert(path)``, the call the
``indra-ocr`` command makes, so decoding (OpenCV, in grayscale), orientation, deskew, detection, recognition, layout
and reading order are the package's. Decoding the file itself matters: on the BHL OCR board's 60-page sample (lossless
WebP) the package read 54 of 60 pages to the board's text from the file and 26 from a PNG of the decoded RGB pixels
(NOTES.md). The settings are ``indra_ocr.load()``'s: ``mode``, ``furniture`` (page headers and footers
in the Markdown), ``math``, ``dpi`` (PDFs only) and ``threads`` (ONNX Runtime threads; one per task, as the package's
``convert_many`` runs one single-threaded worker per core). The models are the catalog's pin of
``datalab-to/indra-ocr`` (the model set ``v1.1.0`` that ``indra-ocr`` 1.1.2 is built against), every file checked.

The page's Markdown (``page.markdown``) is its text, verbatim (``extra["raw"]``); the package's layout blocks (label,
box in pixels, text), its rotation and skew are kept next to it. A page the package reports as failed
(``source == "error"``) is the page's error. An empty Markdown (a blank leaf) is a transcription without text.
"""
from __future__ import annotations

import io
import os
import tempfile
from typing import ClassVar, Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from linecaster.data import Line, Source, StepInfo, Transcription
from linecaster.engines.api import hf_snapshot


class IndraRecognitionEngine:
    """linecaster engine for the recognition step: Indra OCR (Datalab's ONNX pipeline of detector, orientation,
    script classifier, line recognizers, layout and reading order) on the whole page, on the CPU, from the page
    image's file (``image_input = "bytes"``). Returns the page's Markdown as a text-only transcription; the models are
    ``weights`` (the catalog pin), else the package's own model set."""

    engine_id: ClassVar[str] = "indra.recognition.v1"
    step = "recognition"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["lines", "text", "markdown"]}
    #: the page image's file bytes, not an RGB array: the package decodes the file itself
    image_input: ClassVar[str] = "bytes"

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        mode: Literal["auto", "ocr", "text"] = Field("auto", description="the package's mode: auto (an image is "
                                                                          "OCR'd; a PDF uses its text layer where it "
                                                                          "has one), ocr, text")
        furniture: bool = Field(False, description="keep page headers and footers in the Markdown")
        math: bool = Field(False, description="write math as LaTeX (the math models; slower)")
        dpi: float = Field(200.0, description="the resolution PDF pages are rendered at (images are read as they "
                                              "are)")
        threads: int = Field(1, ge=1, description="ONNX Runtime threads (one per task, as the package's own "
                                                  "workers)")

    def __init__(self, mode: str = "auto", furniture: bool = False, math: bool = False, dpi: float = 200.0,
                 threads: int = 1, weights: dict | None = None):
        o = self.Options(mode=mode, furniture=furniture, math=math, dpi=dpi, threads=threads)
        self.options, self.weights = o, weights
        self.name = "datalab-to/indra-ocr"
        self.revision: str | None = weights["revision"] if weights else None
        self.converter = None

    def load(self) -> None:
        import indra_ocr

        o = self.options
        path = str(hf_snapshot(self.weights)) if self.weights is not None else None
        self.converter = indra_ocr.load(path=path, threads=o.threads, dpi=o.dpi, mode=o.mode, furniture=o.furniture,
                                        math=o.math)
        self.version = indra_ocr.__version__

    def read(self, data: bytes):
        """The package's ``Page`` for the page image (its file's bytes), read from a temporary file."""
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "PNG").lower()
        fd, path = tempfile.mkstemp(suffix="." + {"jpeg": "jpg", "jpeg2000": "jp2"}.get(fmt, fmt))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            pages = list(self.converter.convert(path))
        finally:
            os.unlink(path)
        if len(pages) != 1:
            raise RuntimeError(f"indra-ocr read {len(pages)} pages from one page image")
        return pages[0][1]

    def __call__(self, image: bytes, transcription: Transcription, **params) -> Transcription:
        page = self.read(image)
        if page.source == "error":
            raise RuntimeError(f"indra-ocr failed on the page: {page.note}")
        raw = page.markdown or ""
        o = self.options
        lines = [Line(id=f"l{i}", reading_order=i, text=t) for i, t in enumerate(raw.split("\n"))]
        step = StepInfo(step=self.step, name=self.name, engine=self.engine_id, revision=self.revision,
                        backend=f"indra-ocr {self.version} (ONNX Runtime, cpu)",
                        settings=o.model_dump(mode="json"), measurements={"device": "cpu"})
        blocks = [{"label": b.get("label"), "bbox": [round(float(v), 1) for v in b.get("bbox") or []],
                   "text": b.get("text")} for b in (page.blocks or [])]
        return Transcription(lines=lines, steps=[step], source=Source(kind="produced", format="text"),
                             extra={"raw": raw, "source": page.source, "note": page.note, "blocks": blocks,
                                    "rotation": page.rotation, "skew": page.skew})
