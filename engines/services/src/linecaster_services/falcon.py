"""Falcon-OCR's whole-page product: the vendor's pipeline service (``ghcr.io/tiiuae/falcon-ocr``: vLLM with the
Falcon-OCR model on port 8000, the layout and assembly pipeline on 5002), one page per request.

Falcon-OCR is a crop model by design: the pipeline detects the layout, reads each crop with a category prompt and
assembles the page's Markdown. The engine sends the page as the BHL OCR board's driver does: RGB, scaled down so its
longest side is at most ``longest_edge`` (LANCZOS), JPEG at ``jpeg_quality``, as a data URI to
``POST /falconocr/parse`` with ``skip_layout`` (``false``: the vendor's full-page path). The answer's
``markdown_result`` is the page's text, verbatim; its layout regions (``json_result``) are kept next to it. The
service reports no finish reason; its output tokens are the step's ``completion_tokens``.
"""
from __future__ import annotations

import base64
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from linecaster.data import StepInfo, Transcription

from . import http
from .page import jpeg, rgb, text_transcription


class FalconRecognitionEngine:
    """linecaster engine for the recognition step: a whole page through Falcon-OCR's pipeline service (layout, a
    request per crop, the vendor's Markdown assembly), behind its HTTP API. The service runs in the vendor's image
    (``ServiceServer`` starts it); the engine is its client, in the pipeline's process."""

    engine_id: ClassVar[str] = "falcon.recognition.v1"
    step = "recognition"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["lines", "text", "markdown"]}
    route: ClassVar[str] = "/falconocr/parse"

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        endpoint: str = Field("http://127.0.0.1:5002", description="the pipeline service's base URL (the vendor "
                                                                   "image's port 5002, on loopback)")
        longest_edge: int = Field(2048, description="the page is scaled down (LANCZOS, never up) so its longest side "
                                                    "is at most this many pixels before it is sent")
        jpeg_quality: int = Field(95, description="the JPEG quality the page is sent at")
        skip_layout: bool = Field(False, description="the vendor's direct VLM path without layout detection; false: "
                                                     "the full-page pipeline (layout, crops, assembly)")
        timeout: float = Field(1800.0, description="seconds a page's request may take")

    def __init__(self, endpoint: str = "http://127.0.0.1:5002", longest_edge: int = 2048, jpeg_quality: int = 95,
                 skip_layout: bool = False, timeout: float = 1800.0, weights: dict | None = None):
        o = self.Options(endpoint=endpoint, longest_edge=longest_edge, jpeg_quality=jpeg_quality,
                         skip_layout=skip_layout, timeout=timeout)
        self.options, self.weights = o, weights
        self.name = "tiiuae/Falcon-OCR"
        self.revision: str | None = weights["revision"] if weights else None

    def load(self) -> None:
        """Checks that the service answers (``GET /health``); it holds the model."""
        status = http.get(f"{self.options.endpoint.rstrip('/')}/health")
        if status != 200:
            raise ConnectionError(f"Falcon-OCR's pipeline service at {self.options.endpoint} does not answer "
                                  f"/health (status {status}): start it (ServiceServer) or give its endpoint")

    def request(self, image) -> dict:
        """The request body for one page (an RGB array)."""
        o = self.options
        b64 = base64.b64encode(jpeg(rgb(image), o.longest_edge, o.jpeg_quality)).decode()
        return {"images": [f"data:image/jpeg;base64,{b64}"], "skip_layout": o.skip_layout}

    def parse(self, body: dict) -> Transcription:
        """The service's answer as the page's transcription: ``markdown_result`` verbatim; none is an error."""
        raw = body.get("markdown_result")
        if not isinstance(raw, str):
            raise http.ServiceError(f"Falcon-OCR answered without markdown_result: {sorted(body)}")
        o = self.options
        tokens = body.get("total_output_tokens")
        step = StepInfo(step=self.step, name=self.name, engine=self.engine_id, revision=self.revision,
                        backend=f"Falcon-OCR pipeline service ({o.endpoint})",
                        settings={"route": self.route, "skip_layout": o.skip_layout, "longest_edge": o.longest_edge,
                                  "jpeg_quality": o.jpeg_quality},
                        measurements={"completion_tokens": tokens if isinstance(tokens, int) else None})
        return text_transcription(raw, step, regions_json=body.get("json_result"),
                                  processing_ms=body.get("processing_time_ms"))

    def __call__(self, image, transcription: Transcription, **params) -> Transcription:
        o = self.options
        body = http.post_json(f"{o.endpoint.rstrip('/')}{self.route}", self.request(image), o.timeout)
        return self.parse(body)
