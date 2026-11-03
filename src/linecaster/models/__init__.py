"""Model specs for VLMs served behind an OpenAI-compatible chat endpoint (vLLM, SGLang, ...).

A spec is everything model-specific about running a page-recognition VLM through ``ChatPageStep``
(``linecaster.blocks.chat``): how to turn a page image into a ``/chat/completions`` request, how to
turn the response into a text-only ``Transcription``, and the server (vLLM by default, or SGLang) and
the flags the model wants. The
block itself is generic. Specs are plain picklable objects (datatrove dill-pickles the pipeline)
and import neither vLLM nor torch: only Pillow, to re-encode the image.

Specs live here, in the core, one module per model (``lighton_ocr2.py``), because they are small
and dependency-free; a model that needs heavy client-side code would get a backend instead.
``CHAT_MODELS`` maps the served model id to its spec class.
"""
from __future__ import annotations

import base64
import io
from typing import Any, ClassVar

from ..transcription.model import Line, ModelInfo, Source, Transcription


class ChatModel:
    """Base class of a chat-VLM spec. Subclasses set ``model`` (the Hub id, also the name the server
    hosts it under unless ``served_name`` is given), ``revision``, ``sampling`` and ``serve_args`` and
    implement ``request``; ``parse`` has a text-only default."""

    model: ClassVar[str]
    revision: ClassVar[str | None] = None
    sampling: ClassVar[dict[str, Any]] = {}
    serve_args: ClassVar[list[str]] = []          # server flags after the model (not port/host)
    vllm_version: ClassVar[str | None] = None     # the vLLM release the spec was validated with
    #: the OpenAI-compatible server ``ServeChatModel`` starts for this model: ``"vllm"`` (``vllm serve``) or
    #: ``"sglang"`` (``python -m sglang.launch_server``); ``serve_args`` are that server's flags
    server: ClassVar[str] = "vllm"
    server_env: ClassVar[dict[str, str]] = {}     # environment variables for the server process
    #: pass ``--revision`` to the server. ``False`` for a server that must load the default branch: the serve
    #: block then checks that the default branch's files equal the pinned revision's (``pin_ignore`` aside)
    revision_flag: ClassVar[bool] = True
    pin_ignore: ClassVar[tuple[str, ...]] = ("README.md", ".gitattributes")
    step: ClassVar[str] = "page"
    page_longest: ClassVar[int | None] = None     # the page size the model expects (longest side, px), if any

    def __init__(self, served_name: str | None = None):
        self.served_name = served_name or self.model

    # ------------------------------------------------------------- request
    def request(self, image: bytes) -> dict:  # pragma: no cover - interface
        """The ``/chat/completions`` body for one page image (the image file's bytes)."""
        raise NotImplementedError

    region_pad: ClassVar[int | None] = None       # crop padding (px at page scale); None = the block's default

    def request_region(self, crop: bytes, region=None) -> dict:
        """The body for a crop of one region (``ChatRegionStep``), already scaled by the block to the page
        scale the model expects (``page_longest``): sent as it is. ``region`` is the ``Region`` it was cut
        from (a spec may choose its prompt by the region's type). Default: ``request(crop)``."""
        return self.request(crop)

    def reads_region(self, region, labels) -> bool:
        """Whether ``ChatRegionStep`` sends this region to the model. Default: its label is in ``labels``."""
        return region.label in labels

    def crop_region(self, image, region, scale: float = 1.0, pad: int = 0):
        """The crop of ``region`` from the page ``image`` (already scaled by ``scale``): the region's box at
        that scale with ``pad`` px around it. A spec overrides it to follow its model's own crop rule."""
        from ..geometry import bbox_of

        b = bbox_of(region.polygon)
        box = (max(0, int((b.x0 - pad) * scale)), max(0, int((b.y0 - pad) * scale)),
               min(image.width, int((b.x1 + pad) * scale + 0.999)), min(image.height, int((b.y1 + pad) * scale + 0.999)))
        return image.crop(box)

    def settings(self) -> dict[str, Any]:
        """Everything that decides the output, recorded in ``ModelInfo.settings``."""
        return {"sampling": dict(self.sampling), "serve_args": list(self.serve_args)}

    def vllm_args(self, gpu_memory_utilization: float | None = None, extra: list[str] | None = None) -> list[str]:
        """``vllm serve`` arguments after the model id: the revision, the spec's flags, and overrides."""
        return self._server_args("--gpu-memory-utilization", gpu_memory_utilization, extra)

    def sglang_args(self, mem_fraction_static: float | None = None, extra: list[str] | None = None) -> list[str]:
        """``sglang.launch_server`` arguments after ``--model-path <model>``: the revision, the spec's flags,
        and overrides (``--mem-fraction-static`` is SGLang's share of GPU memory)."""
        return self._server_args("--mem-fraction-static", mem_fraction_static, extra)

    def _server_args(self, memory_flag: str, memory: float | None, extra: list[str] | None) -> list[str]:
        args = ["--revision", self.revision] if self.revision and self.revision_flag else []
        if self.served_name != self.model:
            args += ["--served-model-name", self.served_name]
        args += list(self.serve_args)
        if memory is not None:
            args += [memory_flag, str(memory)]
        return args + list(extra or [])

    def server_packages(self) -> list[list[str]]:
        """Packages the serve block installs into the server's Python before it starts, one
        ``uv pip install`` argument list each (e.g. a patched server wheel). Default: none."""
        return []

    # --------------------------------------------------------------- parse
    def content(self, body: dict) -> tuple[str, str | None]:
        """The completion verbatim (``None`` content counts as empty) and its finish reason."""
        choices = body.get("choices") or []
        if not choices:
            raise ValueError(f"no choices in response: {body!r}"[:500])
        return choices[0]["message"].get("content") or "", choices[0].get("finish_reason")

    def parse(self, body: dict, backend: str | None = None) -> Transcription:
        """A text-only transcription: one line per text line of the completion, no geometry. The raw
        completion is kept verbatim in ``extra["raw"]`` (``Transcription.text`` equals it, since lines
        are split on ``\\n`` and joined back), so post-processing can be decided later."""
        raw, finish = self.content(body)
        usage = body.get("usage") or {}
        return text_transcription(raw, ModelInfo(
            step=self.step, name=self.model, revision=self.revision, backend=backend,
            settings=self.settings(),
            measurements={"prompt_tokens": usage.get("prompt_tokens"),
                          "completion_tokens": usage.get("completion_tokens"),
                          "finish_reason": finish}), finish_reason=finish)


def text_transcription(raw: str, model: ModelInfo | None = None, finish_reason: str | None = None) -> Transcription:
    lines = [Line(id=f"l{i}", reading_order=i, text=t) for i, t in enumerate(raw.split("\n"))]
    return Transcription(lines=lines, model=[model] if model else [],
                         source=Source(kind="produced", format="text"),
                         extra={"raw": raw, "finish_reason": finish_reason})


def png_longest(image: bytes, longest: int) -> tuple[str, tuple[int, int]]:
    """RGB, longest side forced to exactly ``longest`` px (up or down, LANCZOS), base64 PNG; and the size."""
    from PIL import Image

    with Image.open(io.BytesIO(image)) as im:
        img = im.convert("RGB")
    w, h = img.size
    if max(w, h) != longest:
        scale = longest / max(w, h)
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode(), img.size


def _registry() -> dict[str, type[ChatModel]]:
    from .dots_mocr import DotsMOCR
    from .glm_ocr import GLMOCR
    from .lighton_ocr2 import LightOnOCR2
    from .lighton_ocr3 import LightOnOCR3, LightOnOCR3Small
    from .minicpm_ocr import MiniCPMOCR
    from .olmocr2 import OlmOCR2
    from .paddleocr_vl import PaddleOCRVL16
    from .unlimited_ocr import UnlimitedOCR, UnlimitedOCR2

    return {cls.model: cls for cls in (DotsMOCR, GLMOCR, LightOnOCR2, LightOnOCR3, LightOnOCR3Small, MiniCPMOCR, OlmOCR2,
                                       PaddleOCRVL16, UnlimitedOCR, UnlimitedOCR2)}


def chat_model(model: str, **kwargs) -> ChatModel:
    """The spec for a served model id, e.g. ``chat_model("lightonai/LightOnOCR-2-1B")``."""
    return _registry()[model](**kwargs)


__all__ = ["ChatModel", "chat_model", "png_longest", "text_transcription"]
