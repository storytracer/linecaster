"""Page recognition by a VLM behind an OpenAI-compatible chat server (vLLM, SGLang, a hosted endpoint).

``ChatPageStep`` is a served ``ModelStep`` whose route is ``/chat/completions`` instead of
``linecaster serve``'s ``/linecaster/{step}``: the same saturate machinery (``AdaptiveClient`` +
``through()``: a window of pages in flight, adapted to the engine's queue gauges, 429s and delivered
tokens; results passed on as they finish), with a model spec (``linecaster.models``) building the
request from the page image and parsing the completion into a text-only ``Transcription``.

    from linecaster.backends import Served
    from linecaster.models import chat_model

    spec = chat_model("lightonai/LightOnOCR-2-1B")
    ChatPageStep(spec, Served("http://127.0.0.1:8000/v1", model=spec.model, max_window=48, initial_window=8))

The completion is kept verbatim (``Transcription.extra["raw"]``, and ``text`` equals it); its
``finish_reason`` and token counts go to ``extra`` and ``ModelInfo.measurements``. A completion cut
off at ``max_tokens`` (``finish_reason == "length"``, on page OCR nearly always a repetition loop) is
stored like any other and counted in the block's stats (``finish_length``); deciding what it means is
for whoever scores or post-processes the text. A request that fails is recorded on the page as an
error (``doc.metadata["errors"]``), as for every model block.

``saturate`` reads the response's ``usage`` itself, so the window controller sees delivered tokens.
"""
from __future__ import annotations

from ..backends import Served
from ..models import ChatModel
from .base import image_bytes
from .models import ModelStep


class ChatPageStep(ModelStep):
    """Recognise every page with a chat VLM; the result is the page's ``transcription`` (default ``ocr``).

    ``backend.model`` is the name the server hosts the model under (for vLLM without
    ``--served-model-name``: the Hub id, ``spec.model``). ``prepare_workers`` threads build requests
    ahead of admission (decode, resize and PNG-encode the image; Pillow releases the GIL)."""

    step = "page"
    route = "/chat/completions"

    def __init__(self, spec: ChatModel, backend: Served, transcription: str = "ocr", primary: str | None = None,
                 skip_on_error: bool = True, prepare_workers: int = 4):
        if not getattr(backend, "served", False):
            raise TypeError("ChatPageStep needs a Served backend (an OpenAI-compatible chat endpoint)")
        super().__init__(backend, transcription, None, primary, skip_on_error,
                         name=f"page ({spec.model}, served {backend.endpoint})")
        spec.served_name = backend.model
        self.spec, self.prepare_workers = spec, prepare_workers

    def process_page(self, doc, page):  # pragma: no cover - only reached with an in-process backend
        raise TypeError("ChatPageStep runs served only")

    def _request(self, row: dict) -> dict:
        return self.spec.request(image_bytes(row["doc"]))

    def _parse(self, body: dict) -> dict:
        t = self.spec.parse(body, backend=self.backend.describe())
        return {"transcription": t.model_dump(mode="json"), "usage": body.get("usage") or {}}
