"""Chat-VLM adapters: page and region recognition by VLMs behind an OpenAI-compatible chat endpoint (vLLM,
SGLang, ...), configured by catalogue presets (``docs/reference/catalog.md``).

Everything about a model that is data lives in its preset (``linecaster/catalog/data/presets/<id>.md``,
``engine: chat.v1``): the model pin, the served name, sampling, prompts, page size, region padding, the
server (vLLM or SGLang), its version, flags, environment and packages, the HF Jobs image it was validated
with. What stays code is the **adapter** the preset names (``options.adapter``): how a page image
becomes a ``/chat/completions`` request, how the completion becomes a text-only ``Transcription``, which
regions are read and how they are cut, and helpers such as an answer format's Markdown conversion. Models
that share that code share an adapter (both DeepSeek-OCRs, both LightOnOCR-3s, both dots, both Ovis).

``chat_model(ref)`` is the one way in: a preset ref (``dots-ocr``, ``dots-ocr@1``) or, for compatibility, the
Hugging Face id (``rednote-hilab/dots.ocr``, the model's page preset). It returns a configured adapter, the
object ``ChatPageStep`` / ``ChatRegionStep`` and ``ServeChatModel`` take: plain and picklable (datatrove
dill-pickles the pipeline), importing neither vLLM nor torch (only Pillow, to re-encode the image).

Adapters register by name in ``ADAPTERS`` (``adapters()``), one module per answer format or family.
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from typing import Any, ClassVar

from ..data.transcription import Line, ModelInfo, Source, Transcription

#: the engine of chat presets
ENGINE = "chat.v1"
#: files ``check_default_branch`` ignores by default
PIN_IGNORE = ("README.md", ".gitattributes")


@dataclass(frozen=True)
class ChatPreset:
    """A resolved chat preset edition, as an adapter is built from it."""

    ref: str                                     # id@edition
    sha256: str | None                           # its functional content's hash (catalog.lock)
    repo: str                                    # the model's Hugging Face id (also the default served name)
    revision: str | None
    step: str = "page"                           # the preset's step: page, or recognition (region by region)
    options: dict = field(default_factory=dict)  # the preset's options
    settings: dict = field(default_factory=dict)
    serve: dict = field(default_factory=dict)    # the serve block
    draft: dict | None = None                    # a speculative-decoding draft: repo, revision, its config


class ChatModel:
    """Base class of a chat-VLM adapter. A subclass sets ``adapter`` (its registry name) and implements
    ``request``; ``parse`` has a text-only default. Every value comes from the preset:

    * ``model`` / ``revision``: the Hugging Face id and pinned commit; ``served_name``: the name the server
      hosts it under (``options.served_name``, default the Hub id);
    * ``sampling``, ``prompt``, ``page_longest`` (the page size the model expects, longest side in px; also
      the scale ``ChatRegionStep`` cuts regions at), ``region_pad`` and the adapter's own ``settings``;
    * ``server`` (``vllm`` or ``sglang``), ``server_version``, ``job_image``, ``serve_args`` (the server's
      flags after the model, not port/host) and ``server_env`` from the ``serve`` block;
    * ``revision_flag`` (pass ``--revision``; ``False`` for a server that must load the default branch, which
      the serve block then checks file by file against the pin, ``pin_ignore`` aside) and
      ``server_packages`` (installed into the server's Python first) from the serve block or, until the
      serve schema has them, ``options``."""

    adapter: ClassVar[str]

    def __init__(self, preset: ChatPreset, served_name: str | None = None):
        p = preset
        self.preset, self.preset_sha256 = p.ref, p.sha256
        self.model, self.revision = p.repo, p.revision
        self.step = "regions" if p.step == "recognition" else "page"
        self.options, self.config, serve = dict(p.options), dict(p.settings), dict(p.serve or {})
        self.sampling: dict[str, Any] = dict(self.config.get("sampling") or {})
        self.prompt: str | None = self.config.get("prompt")
        self.page_longest: int | None = self.config.get("page_longest")
        self.region_pad: int | None = self.config.get("region_pad")
        self.server: str = serve.get("server", "vllm")
        self.server_version: str | None = serve.get("version")
        self.job_image: str | None = serve.get("image")
        self.serve_args: list[str] = list(serve.get("flags") or [])
        self.server_env: dict[str, str] = dict(serve.get("env") or {})

        def server_option(key, default):
            return serve[key] if key in serve else self.options.get(key, default)

        self.revision_flag: bool = bool(server_option("revision_flag", True))
        self.pin_ignore: tuple[str, ...] = tuple(server_option("pin_ignore", PIN_IGNORE))
        self._server_packages = [list(a) for a in server_option("server_packages", [])]
        self.served_name = served_name or self.options.get("served_name") or self.model
        if p.draft:
            self.draft_model, self.draft_revision = p.draft["repo"], p.draft.get("revision")
            self.draft_config: dict[str, Any] = dict(p.draft.get("speculative") or {})

    @property
    def vllm_version(self) -> str | None:
        """The vLLM release the preset was validated with (``None`` for another server)."""
        return self.server_version if self.server == "vllm" else None

    def flag(self, name: str) -> str | None:
        """The value of server flag ``name`` in the preset's flags (``None`` if absent)."""
        args = self.serve_args
        return args[args.index(name) + 1] if name in args else None

    # ------------------------------------------------------------- request
    def request(self, image: bytes) -> dict:  # pragma: no cover - interface
        """The ``/chat/completions`` body for one page image (the image file's bytes)."""
        raise NotImplementedError

    def request_region(self, crop: bytes, region=None) -> dict:
        """The body for a crop of one region (``ChatRegionStep``), already scaled by the block to the page
        scale the model expects (``page_longest``): sent as it is. ``region`` is the ``Region`` it was cut
        from (an adapter may choose its prompt by the region's type). Default: ``request(crop)``."""
        return self.request(crop)

    def reads_region(self, region, labels) -> bool:
        """Whether ``ChatRegionStep`` sends this region to the model. Default: its label is in ``labels``."""
        return region.label in labels

    def crop_region(self, image, region, scale: float = 1.0, pad: int = 0):
        """The crop of ``region`` from the page ``image`` (already scaled by ``scale``): the region's box at
        that scale with ``pad`` px around it. An adapter overrides it to follow its model's own crop rule."""
        from ..data.geometry import bbox_of

        b = bbox_of(region.polygon)
        box = (max(0, int((b.x0 - pad) * scale)), max(0, int((b.y0 - pad) * scale)),
               min(image.width, int((b.x1 + pad) * scale + 0.999)), min(image.height, int((b.y1 + pad) * scale + 0.999)))
        return image.crop(box)

    def settings(self) -> dict[str, Any]:
        """Everything that decides the output, recorded in ``ModelInfo.settings`` (next to the preset edition
        and its hash)."""
        return {"sampling": dict(self.sampling), "serve_args": list(self.serve_args)}

    # -------------------------------------------------------------- server
    def vllm_args(self, gpu_memory_utilization: float | None = None, extra: list[str] | None = None) -> list[str]:
        """``vllm serve`` arguments after the model id: the revision, the preset's flags, and overrides."""
        if self.server != "vllm":
            name = {"sglang": "SGLang"}.get(self.server, self.server)
            raise TypeError(f"{self.model} has no vLLM support; it runs on {name} ({self.server}_args)")
        return self._server_args("--gpu-memory-utilization", gpu_memory_utilization, extra)

    def sglang_args(self, mem_fraction_static: float | None = None, extra: list[str] | None = None) -> list[str]:
        """``sglang.launch_server`` arguments after ``--model-path <model>``: the revision, the preset's flags,
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
        ``uv pip install`` argument list each (e.g. a patched server wheel); ``{repo}`` and ``{revision}`` in
        the preset's entries are the model's. Default: none."""
        return [[a.format(repo=self.model, revision=self.revision) for a in args] for args in self._server_packages]

    # --------------------------------------------------------------- parse
    def content(self, body: dict) -> tuple[str, str | None]:
        """The completion verbatim (``None`` content counts as empty) and its finish reason."""
        choices = body.get("choices") or []
        if not choices:
            raise ValueError(f"no choices in response: {body!r}"[:500])
        return choices[0]["message"].get("content") or "", choices[0].get("finish_reason")

    def model_info(self, backend: str | None = None, settings: dict | None = None,
                   measurements: dict | None = None) -> ModelInfo:
        """The ``ModelInfo`` of one result: model, revision, preset edition and its hash, settings."""
        return ModelInfo(step=self.step, name=self.model, revision=self.revision, preset=self.preset,
                         preset_sha256=self.preset_sha256, backend=backend,
                         settings=self.settings() if settings is None else settings, measurements=measurements or {})

    def parse(self, body: dict, backend: str | None = None) -> Transcription:
        """A text-only transcription: one line per text line of the completion, no geometry. The raw
        completion is kept verbatim in ``extra["raw"]`` (``Transcription.text`` equals it, since lines
        are split on ``\\n`` and joined back), so post-processing can be decided later."""
        raw, finish = self.content(body)
        usage = body.get("usage") or {}
        return text_transcription(raw, self.model_info(backend, measurements={
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
            "finish_reason": finish}), finish_reason=finish)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.preset} ({self.model}@{(self.revision or '')[:8]})>"


def text_transcription(raw: str, model: ModelInfo | None = None, finish_reason: str | None = None) -> Transcription:
    lines = [Line(id=f"l{i}", reading_order=i, text=t) for i, t in enumerate(raw.split("\n"))]
    return Transcription(lines=lines, model=[model] if model else [],
                         source=Source(kind="produced", format="text"),
                         extra={"raw": raw, "finish_reason": finish_reason})


def data_url(mime: str, b64: str) -> dict:
    """An ``image_url`` content part."""
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def png_bytes(img) -> str:
    """Base64 PNG of a Pillow image."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def png_longest(image: bytes, longest: int) -> tuple[str, tuple[int, int]]:
    """RGB, longest side forced to exactly ``longest`` px (up or down, LANCZOS), base64 PNG; and the size."""
    from PIL import Image

    with Image.open(io.BytesIO(image)) as im:
        img = im.convert("RGB")
    w, h = img.size
    if max(w, h) != longest:
        scale = longest / max(w, h)
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    return png_bytes(img), img.size


# ------------------------------------------------------------------------------------------------ registry

#: adapter name -> ``module:Class`` (modules import lazily)
ADAPTERS = {
    "chandra-ocr": "chandra_ocr2:ChandraOCR",
    "deepseek-ocr": "deepseek_ocr:DeepSeekOCR",
    "dots": "dots:Dots",
    "glm-ocr": "glm_ocr:GLMOCR",
    "lighton-ocr-2": "lighton_ocr2:LightOnOCR2",
    "lighton-ocr-3": "lighton_ocr3:LightOnOCR3",
    "minicpm-ocr": "minicpm_ocr:MiniCPMOCR",
    "nemotron-parse": "nemotron_parse35:NemotronParse",
    "olmocr": "olmocr2:OlmOCR",
    "ovis-ocr": "ovis_ocr:OvisOCR",
    "paddleocr-vl": "paddleocr_vl:PaddleOCRVL",
    "qianfan-ocr": "qianfan_ocr:QianfanOCR",
    "qwen3.5": "qwen35:Qwen35",
    "smoldocling": "smoldocling:SmolDocling",
    "unlimited-ocr": "unlimited_ocr:UnlimitedOCR",
    "unlimited-ocr-2": "unlimited_ocr:UnlimitedOCR2",
}


def adapter(name: str) -> type[ChatModel]:
    """The adapter class registered under ``name``."""
    from importlib import import_module

    if name not in ADAPTERS:
        raise KeyError(f"unknown chat adapter {name!r}; known: {sorted(ADAPTERS)}")
    module, _, cls = ADAPTERS[name].partition(":")
    return getattr(import_module(f"{__name__}.{module}"), cls)


def adapters() -> dict[str, type[ChatModel]]:
    return {name: adapter(name) for name in ADAPTERS}


def chat_presets(catalog=None) -> dict[str, str]:
    """Chat preset ids -> the model's Hugging Face id."""
    from ..catalog.registry import catalog as installed

    c = catalog or installed()
    return {pid: c.model(p.model.id).source.ref for pid, (_, p) in sorted(c.presets.items())
            if p.engine == ENGINE and p.model is not None}


def preset_ref(ref: str, catalog=None, prefer: str = "page") -> str:
    """``ref`` as a preset ref: a preset id[@edition] as it is; a Hugging Face id becomes one of that model's
    presets, the first in id order with step ``prefer`` (``page``, or ``recognition`` for region reading), else
    the first in id order."""
    from ..catalog.registry import catalog as installed

    c = catalog or installed()
    if ref.split("@", 1)[0] in c.presets:
        return ref
    ids = [pid for pid, repo in chat_presets(c).items() if repo == ref]
    if not ids:
        raise KeyError(f"no chat preset for {ref!r}; chat presets: {sorted(chat_presets(c))}")
    return sorted(ids, key=lambda pid: (c.preset(pid).step != prefer, pid))[0]


def chat_model(ref: str, served_name: str | None = None, catalog=None, prefer: str = "page") -> ChatModel:
    """The configured adapter for a chat preset: ``chat_model("lightonocr-2-1b")``, ``chat_model("dots-ocr@1")``,
    or by Hugging Face id, ``chat_model("lightonai/LightOnOCR-2-1B")`` (its page preset; ``prefer="recognition"``:
    its region preset)."""
    from ..catalog.registry import catalog as installed

    c = catalog or installed()
    r = c.resolve(preset_ref(ref, c, prefer))
    content = r.content
    engine = content.get("engine")
    if engine != ENGINE:
        raise ValueError(f"preset {r.ref} is not a chat preset (engine {engine!r}, not {ENGINE})")
    options = dict(content.get("options") or {})
    m = c.model(content["model"]["id"])
    draft = None
    serve = dict(content.get("serve") or {})
    if serve.get("draft"):
        d = dict(serve["draft"])
        dm = c.model(d["model"])
        dm.pin(d["revision"])                   # the draft's revision must be pinned in its model document
        draft = {"repo": dm.source.ref, "revision": d["revision"], "speculative": d.get("speculative") or {}}
    preset = ChatPreset(ref=r.ref, sha256=r.sha256, repo=m.source.ref, revision=content["model"]["revision"],
                        step=content["step"], options=options, settings=dict(content.get("settings") or {}),
                        serve=dict(content.get("serve") or {}), draft=draft)
    return adapter(options["adapter"])(preset, served_name=served_name)


__all__ = ["ADAPTERS", "ChatModel", "ChatPreset", "ENGINE", "adapter", "adapters", "chat_model", "chat_presets",
           "png_longest", "preset_ref", "text_transcription"]
