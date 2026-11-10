"""OXR's whole-page product: the vendor's all-in-one service (an image built from SoMarkAI/OXR's
``docker/Dockerfile.allinone``: vLLM with the OXR model on port 8080, the D-FINE layout service on 8081, the ``oxr``
API on 8000), one page per request.

The engine sends the page as RGB, lossless PNG at its own size (the layout model
resizes as it needs), as the file of a multipart ``POST /v1/parse/sync`` with ``api_key`` and one
``output_formats`` field per format (markdown and json, as the vendor's README asks; httpx's encoding of a list).
No ``feature_config`` or ``element_formats`` are sent, so the vendor's defaults apply (page headers and footers
dropped). The API answers 200 with a non-zero ``code`` when the pipeline fails: that is the page's error. The
answer's Markdown is the page's text, verbatim; its blocks (JSON: type, box, content, format) and warnings are kept
next to it. The service reports no finish reason and no token counts.
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from linecaster.data import StepInfo, Transcription

from . import http
from .page import png, rgb, text_transcription


class OxrRecognitionEngine:
    """linecaster engine for the recognition step: a whole page through OXR's all-in-one service (D-FINE layout,
    the OXR VLM per region and its reading order, the vendor's assembly), behind its HTTP API. The service runs in
    the vendor's image (``ServiceServer`` starts it); the engine is its client, in the pipeline's process."""

    engine_id: ClassVar[str] = "oxr.recognition.v1"
    step = "recognition"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["lines", "text", "markdown"]}
    route: ClassVar[str] = "/v1/parse/sync"

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        endpoint: str = Field("http://127.0.0.1:8000", description="the API's base URL (the vendor image's port "
                                                                   "8000, on loopback)")
        output_formats: tuple[str, ...] = Field(("markdown", "json"), description="the formats asked for; the "
                                                                                  "page's text is the markdown")
        timeout: float = Field(1800.0, description="seconds a page's request may take")

    def __init__(self, endpoint: str = "http://127.0.0.1:8000", output_formats: tuple[str, ...] = ("markdown", "json"),
                 timeout: float = 1800.0, weights: dict | None = None):
        o = self.Options(endpoint=endpoint, output_formats=tuple(output_formats), timeout=timeout)
        self.options, self.weights = o, weights
        self.name = "SoMarkAI/OXR-1.0"
        self.revision: str | None = weights["revision"] if weights else None

    def load(self) -> None:
        """Checks that the API answers (``GET /docs``, served once both model services are ready)."""
        status = http.get(f"{self.options.endpoint.rstrip('/')}/docs")
        if status != 200:
            raise ConnectionError(f"OXR's API at {self.options.endpoint} does not answer /docs (status {status}): "
                                  "start it (ServiceServer) or give its endpoint")

    def request(self, image) -> tuple[dict, dict]:
        """The form fields and files for one page (an RGB array)."""
        fields = {"api_key": "dummy", "output_formats": list(self.options.output_formats)}
        return fields, {"file": ("page.png", png(rgb(image)), "image/png")}

    def parse(self, body: dict) -> Transcription:
        """The API's answer as the page's transcription; a failed pipeline (``code`` not 0, or an ``error``) and an
        answer without Markdown are errors."""
        data = body.get("data") or {}
        if body.get("code") != 0 or data.get("error"):
            raise http.ServiceError(f"OXR parse failed: code={body.get('code')} message={body.get('message')!r} "
                                    f"error={data.get('error')!r}")
        outputs = ((data.get("result") or {}).get("outputs")) or {}
        raw = outputs.get("markdown")
        if not isinstance(raw, str):
            raise http.ServiceError(f"OXR answered without markdown: {sorted(outputs)}")
        o = self.options
        step = StepInfo(step=self.step, name=self.name, engine=self.engine_id, revision=self.revision,
                        backend=f"OXR all-in-one service ({o.endpoint})",
                        settings={"route": self.route, "output_formats": list(o.output_formats)})
        return text_transcription(raw, step, blocks_json=outputs.get("json"), warnings=body.get("warnings") or [],
                                  processing_ms=(data.get("metadata") or {}).get("processing_time_ms"))

    def __call__(self, image, transcription: Transcription, **params) -> Transcription:
        o = self.options
        fields, files = self.request(image)
        return self.parse(http.post_form(f"{o.endpoint.rstrip('/')}{self.route}", fields, files, o.timeout))
