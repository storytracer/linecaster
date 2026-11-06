"""Surya OCR 2.5 through the ``surya-ocr`` package's full-page path, as its ``surya_ocr`` command runs it.

``RecognitionPredictor(manager)([page], full_page=True)``: one full-page request per page, the package's parser of the
model's block stream into labelled HTML blocks, its filter of text blocks over blank regions, and, when the full-page
answer is empty on a non-blank page, does not parse, loops or hits the token cap, its block mode (a layout request,
then one request per block). The engine calls exactly that and keeps the result; it reimplements none of it.

The package normally starts ``vllm/vllm-openai`` with ``docker run``. Here it attaches to a running vLLM server
(``SURYA_INFERENCE_URL``, the package's documented attach path) that serves the catalog's pin under the package's
model name: ``ServiceServer`` starts it from the preset, with the flags the package's own launcher passes for
``gpu_type`` (``package_flags``). ``gpu_type`` also sets the package's client concurrency (block mode only). Every
other setting is the package's default (``fullpage_regen`` off, as the package ships it: the regeneration at rising
temperature is opt-in "for benchmarking"). The package reads its settings when it is first imported, so the engine
sets them in the environment before it imports it; one engine per process.

The page's result (the blocks in reading order: label, the model's raw label, reading order, HTML ("" for figures,
which the package does not read), skipped and error flags, confidence, box) is kept verbatim as JSON in
``extra["raw"]``, the format of the BHL OCR board's raw outputs; the text is the blocks' HTML in reading order, one
block per line group. From a wrapper around the package's ``generate``: the full-page completion before parsing, its
finish reason and tokens, the full-page rounds, whether the page fell back to block mode and how many block requests
were capped or failed (``extra``). ``finish_reason`` follows the board: ``length`` when the page keeps a capped block's
partial HTML (the package never keeps a capped full-page answer), else ``stop``. A failed block request is the page's
error.
"""
from __future__ import annotations

import json
import os
import threading
from typing import ClassVar

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from linecaster.data import Line, Source, StepInfo, Transcription

#: the package's model name, which the server must serve the pin under
MODEL = "datalab-to/surya-ocr-2.5"


def package_flags(gpu_type: str) -> list[str]:
    """The vLLM flags the installed ``surya-ocr`` package's launcher passes for ``gpu_type`` (its ``spawn_fn``, without
    the model and the served name), from its own settings and arithmetic; no MTP flag, since the checkpoint declares
    no MTP head."""
    from surya.inference.backends.vllm import _gpu_settings
    from surya.settings import settings

    max_batched_tokens, max_num_seqs = _gpu_settings(gpu_type)
    return ["--no-enforce-eager", "--max-num-seqs", str(max_num_seqs), "--dtype", settings.VLLM_DTYPE,
            "--max-model-len", str(settings.VLLM_MAX_MODEL_LEN), "--max-num-batched-tokens", str(max_batched_tokens),
            "--gpu-memory-utilization", str(settings.VLLM_GPU_MEMORY_UTILIZATION), "--enable-prefix-caching",
            "--mm-processor-kwargs", json.dumps({"min_pixels": 3136, "max_pixels": 6291456})]


def blocks_of(page) -> list[dict]:
    """The package's page result as the board stores it: one dict per block, in reading order."""
    return [{"label": b.label, "raw_label": b.raw_label, "reading_order": b.reading_order, "html": b.html,
             "skipped": b.skipped, "error": b.error, "confidence": b.confidence,
             "bbox": [round(v, 1) for v in b.bbox]} for b in page.blocks]


class SuryaRecognitionEngine:
    """linecaster engine for the recognition step: Surya OCR 2.5 on the whole page through the ``surya-ocr`` package
    (full-page mode with its block-mode fallback), attached to a vLLM server that serves the pinned checkpoint
    (``ServiceServer`` starts it). Returns the page's HTML blocks as a text-only transcription, the package's result
    verbatim as JSON next to it."""

    engine_id: ClassVar[str] = "surya.recognition.v1"
    step = "recognition"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["lines", "text", "html"]}

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        endpoint: str = Field("http://127.0.0.1:8000/v1", description="the vLLM server's .../v1 URL (on loopback), "
                                                                      "which serves the pin under the package's "
                                                                      "model name")
        gpu_type: str = Field("a100-80", description="the package's VLLM_GPU_TYPE: the server flags it implies "
                                                     "(package_flags) and the client's concurrency in block mode")
        fullpage_regen: bool = Field(False, description="the package's SURYA_FULLPAGE_REGEN: ask a looping or "
                                                        "unparseable full-page answer again at rising temperature "
                                                        "before block mode (off by default)")

    def __init__(self, endpoint: str = "http://127.0.0.1:8000/v1", gpu_type: str = "a100-80",
                 fullpage_regen: bool = False, weights: dict | None = None):
        o = self.Options(endpoint=endpoint, gpu_type=gpu_type, fullpage_regen=fullpage_regen)
        self.options, self.weights = o, weights
        self.name = MODEL
        self.revision: str | None = weights["revision"] if weights else None
        self.predictor = None
        self._trace = threading.local()

    def environment(self) -> dict[str, str]:
        """The package's settings, as environment variables (it reads them when it is first imported)."""
        o = self.options
        return {"SURYA_INFERENCE_URL": o.endpoint, "SURYA_INFERENCE_BACKEND": "vllm", "VLLM_GPU_TYPE": o.gpu_type,
                "SURYA_FULLPAGE_REGEN": "true" if o.fullpage_regen else "false", "DISABLE_TQDM": "true"}

    def load(self) -> None:
        os.environ.update(self.environment())
        import surya
        from surya.inference import SuryaInferenceManager
        from surya.recognition import RecognitionPredictor
        from surya.settings import settings

        if settings.SURYA_MODEL_CHECKPOINT != MODEL:
            raise RuntimeError(f"surya-ocr's model is {settings.SURYA_MODEL_CHECKPOINT}, not {MODEL}")
        if settings.SURYA_INFERENCE_URL != self.options.endpoint:
            raise RuntimeError("surya-ocr was imported before the engine set its settings (one engine per process)")
        manager = SuryaInferenceManager(method="vllm")
        manager.start()                                   # attaches; fails when the server does not serve MODEL
        backend, inner = manager.backend, manager.backend.generate

        def traced(batch):              # records what each request returned; the outputs go back unchanged
            outputs = inner(batch)
            calls = getattr(self._trace, "calls", None)
            if calls is not None:
                for item, out in zip(batch, outputs, strict=True):
                    calls.append({"prompt_type": str(item.prompt_type), "raw": out.raw,
                                  "finish_reason": out.finish_reason, "tokens": out.token_count,
                                  "error": bool(out.error)})
            return outputs

        backend.generate = traced
        self.predictor = RecognitionPredictor(manager)
        self.version = getattr(surya, "__version__", None) or _version("surya-ocr")

    def read(self, image: np.ndarray) -> tuple[object, list[dict]]:
        """The package's page result for the page image (an RGB array), with the requests it made."""
        from PIL import Image

        self._trace.calls = []
        try:
            page = self.predictor([Image.fromarray(np.asarray(image, dtype=np.uint8)).convert("RGB")],
                                  full_page=True)[0]
        finally:
            calls, self._trace.calls = self._trace.calls, None
        return page, calls

    def __call__(self, image: np.ndarray, transcription: Transcription, **params) -> Transcription:
        from surya.inference.prompts import PROMPT_TYPE_HIGH_ACCURACY_BBOX

        page, calls = self.read(image)
        full = [c for c in calls if c["prompt_type"] == str(PROMPT_TYPE_HIGH_ACCURACY_BBOX)]
        other = [c for c in calls if c["prompt_type"] != str(PROMPT_TYPE_HIGH_ACCURACY_BBOX)]
        failed = sum(1 for c in other if c["error"])
        if failed:
            raise RuntimeError(f"surya-ocr: {failed} block request(s) failed")
        return self.transcription(blocks_of(page), full, other)

    def transcription(self, blocks: list[dict], full: list[dict], other: list[dict]) -> Transcription:
        """The page's transcription from its blocks and the requests that made them (full-page and block mode)."""
        first = full[0] if full else {}
        capped = any(b["error"] and b["html"] for b in blocks)
        finish = "length" if capped else "stop"
        raw = json.dumps(blocks, ensure_ascii=False)
        text = "\n".join(b["html"] for b in blocks if b["html"])
        tokens = sum(int(c.get("tokens") or 0) for c in [*full, *other])
        o = self.options
        step = StepInfo(step=self.step, name=self.name, engine=self.engine_id, revision=self.revision,
                        backend=f"surya-ocr {getattr(self, 'version', None)} (vLLM {o.endpoint})",
                        settings={"mode": "full_page", "gpu_type": o.gpu_type, "fullpage_regen": o.fullpage_regen},
                        measurements={"completion_tokens": tokens, "finish_reason": finish})
        lines = [Line(id=f"l{i}", reading_order=i, text=t) for i, t in enumerate(text.split("\n"))]
        return Transcription(lines=lines, steps=[step], source=Source(kind="produced", format="text"),
                             extra={"raw": raw, "finish_reason": finish, "fullpage_raw": first.get("raw"),
                                    "fullpage_finish_reason": first.get("finish_reason"),
                                    "fullpage_tokens": first.get("tokens"), "fullpage_rounds": len(full),
                                    "fallback": bool(other), "requests": len(full) + len(other),
                                    "capped_blocks": sum(1 for c in other if c["finish_reason"] == "length")})


def _version(dist: str) -> str | None:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(dist)
    except PackageNotFoundError:
        return None
