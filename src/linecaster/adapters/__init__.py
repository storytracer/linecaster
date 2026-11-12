"""Chat-VLM adapters: page and region recognition by VLMs behind an OpenAI-compatible chat endpoint (vLLM,
SGLang, ...), configured by catalog presets (``docs/reference/catalog.md``).

Everything about a model that is data lives in its preset (``linecaster/catalog/data/presets/<step>/<id>.yaml``,
``engine: chat.v1``): the model pin, the served name, sampling, prompts, page size, region padding, the
server (vLLM or SGLang), its version, flags, environment and packages, the HF Jobs image it was validated
with. What stays code is the **adapter** the preset names (``options.adapter``): how a page image
becomes a ``/chat/completions`` request, how the completion becomes a text-only ``Transcription``, which
regions are read and how they are cut, and helpers such as an answer format's Markdown conversion. Models
that share that code share an adapter (both DeepSeek-OCRs, both LightOnOCR-3s, both dots, both Ovis).

``chat_model(ref)`` is the one way in: a preset ref (``dots-ocr``, ``dots-ocr@1``) or, for compatibility, the
Hugging Face id (``rednote-hilab/dots.ocr``, the model's page preset). It returns a configured adapter, the
object ``PageRecognizer`` / ``RegionRecognizer`` and ``ChatModelServer`` take: plain and picklable (datatrove
dill-pickles the pipeline), importing neither vLLM nor torch (only Pillow, to re-encode the image).

Adapters register by name in ``ADAPTERS`` (``adapters()``), one module per answer format or family.
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..data.transcription import Line, Source, StepInfo, Transcription
from ..errors import CatalogError, PipelineConfigError, ServerError

#: the engine of chat presets
ENGINE = "chat.v1"
#: files ``check_default_branch`` ignores by default
PIN_IGNORE = ("README.md", ".gitattributes")
#: the repair pass's settings where a preset's ``settings.repair`` does not give them: off, and temperature 0.1 (the
#: repair temperature of the reference procedure, uv-scripts/ocr ``lighton-ocr3-saturate.py`` at e2b0aa5,
#: ``SERVING["repair_temperature"]``)
REPAIR_DEFAULTS = {"max_tokens": 0, "temperature": 0.1}
#: options (``ChatAdapter.Options``) -> where they live in a preset's settings
OPTION_SETTINGS = {"max_tokens": ("sampling", "max_tokens"), "temperature": ("sampling", "temperature"),
                   "top_p": ("sampling", "top_p"), "repair_max_tokens": ("repair", "max_tokens"),
                   "repair_temperature": ("repair", "temperature")}


@dataclass(frozen=True)
class ChatPreset:
    """A resolved chat preset edition, as an adapter is built from it."""

    ref: str                                     # id@edition
    sha256: str | None                           # its functional content's hash (catalog.lock)
    repo: str                                    # the model's Hugging Face id (also the default served name)
    revision: str | None
    unit: str = "page"                           # what the preset reads: page, or region (region by region)
    options: dict = field(default_factory=dict)  # the preset's options
    settings: dict = field(default_factory=dict)
    serve: dict = field(default_factory=dict)    # the serve block
    draft: dict | None = None                    # a speculative-decoding draft: repo, revision, its config


class ChatAdapter:
    """Base class of a chat-VLM adapter. A subclass sets ``adapter`` (its registry name) and implements
    ``request``; ``parse`` has a text-only default. Every value comes from the preset:

    * ``model`` / ``revision``: the Hugging Face id and pinned commit; ``served_name``: the name the server
      hosts it under (``options.served_name``, default the Hub id);
    * ``sampling``, ``prompt``, ``page_longest`` (the page size the model expects, longest side in px; also
      the scale ``RegionRecognizer`` cuts regions at), ``region_pad`` and the adapter's own ``settings``;
    * ``server`` (``vllm`` or ``sglang``), ``server_version``, ``job_image``, ``serve_args`` (the server's
      flags after the model, not port/host) and ``server_env`` from the ``serve`` block;
    * ``revision_flag`` (pass ``--revision``; ``False`` for a server that must load the default branch, which
      the serve block then checks file by file against the pin, ``pin_ignore`` aside) and
      ``server_packages`` (installed into the server's Python first) from the serve block or, until the
      serve schema has them, ``options``.

    A run may set the options of ``Options`` over the preset's settings (``chat_model(..., overrides=...)``,
    ``--set recognition.<option>=<value>``): ``max_tokens``, ``temperature`` and ``top_p`` replace the preset's
    ``settings.sampling`` values; ``repair_max_tokens`` and ``repair_temperature`` its ``settings.repair`` values
    (``max_tokens`` and ``temperature``; default off, and 0.1). The values that differ from the preset's are the
    adapter's ``overrides``, recorded with it (``to_dict()``) and so in ``pipeline_sha256``.

    **The repair pass** (``repair_max_tokens`` above 0; ``PageRecognizer`` runs it): a page whose completion stopped
    at ``max_tokens`` (``finish_reason == "length"``) is sent once more, the same request (the same image and prompt,
    the same ``top_p``) with ``max_tokens`` raised to ``repair_max_tokens`` (less where the served context leaves less
    room: ``repair_cap``) and the temperature ``repair_temperature``. The repair's completion is kept where it
    finished (``"stop"``), the first one otherwise, even when the repair's is longer; there is no third request. The
    procedure is the reference script's (uv-scripts/ocr ``lighton-ocr3-saturate.py`` at e2b0aa5, its docstring
    "Truncation and repair"), which repairs at the end of a run; ``PageRecognizer`` repairs a page as soon as its
    first completion is back, with the same outcome. A completion cut off at ``max_tokens`` is often a repetition
    loop, which a repair does not end, but a dense table can simply need more tokens and finish with more room.
    ``repair_max_tokens`` must be larger than ``max_tokens`` (``PipelineConfigError``)."""

    adapter: ClassVar[str]

    class Options(BaseModel):
        """What a run may set over a chat preset's settings (``--set recognition.<option>=<value>``)."""

        model_config = ConfigDict(extra="forbid")

        max_tokens: int | None = Field(None, ge=1, description="the completion's cap (default: the preset's "
                                                                "settings.sampling.max_tokens)")
        temperature: float | None = Field(None, ge=0, description="the sampling temperature (default: the preset's)")
        top_p: float | None = Field(None, gt=0, le=1, description="nucleus sampling (default: the preset's); the "
                                                                   "repair pass keeps it")
        repair_max_tokens: int | list[int] = Field(0, description="the repair passes' caps: a page whose completion "
                                                                  "stopped at max_tokens is sent again with the first "
                                                                  "cap, and again with the next while it stops at its "
                                                                  "cap (a number: one repair; a list: one per pass, "
                                                                  "rising, the first larger than max_tokens; 0 or []: "
                                                                  "off; lightonocr-3-0.8b@3: [8192, 12288], twice and "
                                                                  "three times its 4096)")
        repair_temperature: float = Field(0.1, ge=0, description="the repair pass's temperature (the reference "
                                                                 "script's, uv-scripts/ocr lighton-ocr3-saturate.py "
                                                                 "at e2b0aa5)")

    def __init__(self, preset: ChatPreset, served_name: str | None = None):
        p = preset
        self.preset, self.preset_sha256 = p.ref, p.sha256
        self.model, self.revision = p.repo, p.revision
        self.step, self.unit = "recognition", p.unit
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
        self.repair: dict[str, Any] = {**REPAIR_DEFAULTS, **(self.config.get("repair") or {})}
        self.overrides: dict[str, Any] = {}
        if p.draft:
            self.draft_model, self.draft_revision = p.draft["repo"], p.draft.get("revision")
            self.draft_config: dict[str, Any] = dict(p.draft.get("speculative") or {})

    # ------------------------------------------------------------- options
    def apply_overrides(self, overrides: dict[str, Any] | None) -> ChatAdapter:
        """Set ``Options`` over the preset's settings (``--set recognition.<option>=<value>``); returns the adapter.

        Unknown options and values of the wrong type are a ``PipelineConfigError``; so is a repair pass whose
        ``repair_max_tokens`` is not larger than ``max_tokens``. The values that differ from the preset's are kept
        in ``overrides``."""
        given = dict(overrides or {})
        try:
            checked = self.Options(**given)
        except ValidationError as e:
            problems = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())
            raise PipelineConfigError(f"{self.preset}: {problems} (options: {', '.join(OPTION_SETTINGS)})") from None
        for name in given:
            value = getattr(checked, name)
            where, key = OPTION_SETTINGS[name]
            target = self.sampling if where == "sampling" else self.repair
            if target.get(key) != value:
                target[key] = value
                self.overrides[name] = value
        self.check_repair()
        return self

    @property
    def repair_caps(self) -> tuple[int, ...]:
        """The repair passes' caps in order (``settings.repair.max_tokens``: a number is one pass, 0 none)."""
        value = self.repair.get("max_tokens") or 0
        caps = value if isinstance(value, list | tuple) else [value]
        return tuple(int(c) for c in caps if int(c) > 0)

    @property
    def repair_max_tokens(self) -> int:
        """The largest repair cap (0: no repair pass)."""
        return max(self.repair_caps, default=0)

    @property
    def repair_temperature(self) -> float:
        return float(self.repair["temperature"])

    def check_repair(self) -> None:
        """A repair pass needs a ``max_tokens`` in the sampling and a larger ``repair_max_tokens``."""
        if not self.repair_max_tokens:
            return
        first = self.sampling.get("max_tokens")
        if first is None:
            raise PipelineConfigError(f"{self.preset}: the repair pass needs settings.sampling.max_tokens")
        value = self.repair.get("max_tokens")
        listed = value if isinstance(value, list | tuple) else [value]
        if any(isinstance(c, bool) or not isinstance(c, int) or c < 0 for c in listed):
            raise PipelineConfigError(f"{self.preset}: repair_max_tokens is a number of tokens or a list of them, "
                                      f"not {value!r}")
        caps = self.repair_caps
        if caps[0] <= int(first) or any(b <= a for a, b in zip(caps, caps[1:])):
            raise PipelineConfigError(f"{self.preset}: repair_max_tokens ({', '.join(map(str, caps))}) must rise, "
                                      f"each cap larger than the one before and the first larger than max_tokens "
                                      f"({first})")

    def max_prompt_tokens(self) -> int | None:
        """The most prompt tokens a page can take (its image tokens at the largest page size, and a margin for the
        text), for the check that a repair fits the served context; ``None``: the adapter does not know."""
        return None

    def served_context(self) -> int | None:
        """The context the preset's server flags give the model (``--max-model-len``, vLLM; ``--context-length``,
        SGLang), or ``None``."""
        for flag in ("--max-model-len", "--context-length"):
            value = self.flag(flag)
            if value is not None:
                try:
                    return int(value)
                except ValueError:
                    return None
        return None

    def repair_request(self, body: dict, cap: int) -> dict:
        """The repair pass's request: the first request ``body`` (the same image, prompt and ``top_p``) with
        ``max_tokens`` = ``cap`` and the repair temperature."""
        return {**body, "max_tokens": int(cap), "temperature": self.repair_temperature}

    def repair_cap(self, prompt_tokens: int | None, context: int | None, index: int = 0) -> int:
        """The ``index``-th repair request's ``max_tokens``: that pass's cap (``repair_caps``), at most what the
        context leaves after the page's prompt (``context - prompt_tokens``, where both are known)."""
        cap = self.repair_caps[index]
        if context and prompt_tokens:
            cap = min(cap, int(context) - int(prompt_tokens))
        return cap

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
        """The body for a crop of one region (``RegionRecognizer``), already scaled by the block to the page
        scale the model expects (``page_longest``): sent as it is. ``region`` is the ``Region`` it was cut
        from (an adapter may choose its prompt by the region's type). Default: ``request(crop)``."""
        return self.request(crop)

    def reads_region(self, region, labels) -> bool:
        """Whether ``RegionRecognizer`` sends this region to the model. Default: its label is in ``labels``."""
        return region.label in labels

    def crop_region(self, image, region, scale: float = 1.0, pad: int = 0):
        """The crop of ``region`` from the page ``image`` (already scaled by ``scale``): the region's box at
        that scale with ``pad`` px around it. An adapter overrides it to follow its model's own crop rule."""
        from ..data.geometry import bbox_of

        b = bbox_of(region.polygon)
        box = (max(0, int((b.x0 - pad) * scale)), max(0, int((b.y0 - pad) * scale)),
               min(image.width, int((b.x1 + pad) * scale + 0.999)), min(image.height, int((b.y1 + pad) * scale + 0.999)))
        return image.crop(box)

    def to_dict(self) -> dict[str, Any]:
        """The adapter as the run record names it: the preset edition and its hash, the model and revision, the
        adapter class and the name the server hosts the model under."""
        out = {"adapter": f"{type(self).__module__}:{type(self).__qualname__}", "preset": self.preset,
               "preset_sha256": self.preset_sha256, "model": self.model, "revision": self.revision,
               "served_name": self.served_name}
        if self.overrides:
            out["overrides"] = dict(self.overrides)
        return out

    def settings(self) -> dict[str, Any]:
        """Everything that decides the output, recorded in ``StepInfo.settings`` (next to the preset edition
        and its hash)."""
        return {"sampling": dict(self.sampling), "serve_args": list(self.serve_args)}

    # -------------------------------------------------------------- server
    def vllm_args(self, gpu_memory_utilization: float | None = None, extra: list[str] | None = None) -> list[str]:
        """``vllm serve`` arguments after the model id: the revision, the preset's flags, and overrides."""
        if self.server != "vllm":
            name = {"sglang": "SGLang"}.get(self.server, self.server)
            raise PipelineConfigError(f"{self.model} has no vLLM support; it runs on {name} ({self.server}_args)")
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
            raise ServerError(f"no choices in response: {body!r}"[:500])
        return choices[0]["message"].get("content") or "", choices[0].get("finish_reason")

    def step_info(self, backend: str | None = None, settings: dict | None = None,
                   measurements: dict | None = None) -> StepInfo:
        """The ``StepInfo`` of one result: model, engine, revision, preset edition and its hash, settings (with the
        repair pass's, ``repair``, when it is on)."""
        if settings is None:
            settings = self.settings()
            if self.repair_max_tokens:
                settings["repair"] = {"max_tokens": self.repair_max_tokens, "temperature": self.repair_temperature}
        return StepInfo(step=self.step, name=self.model, engine=ENGINE, revision=self.revision, preset=self.preset,
                        preset_sha256=self.preset_sha256, backend=backend, settings=settings,
                        measurements=measurements or {})

    def parse(self, body: dict, backend: str | None = None) -> Transcription:
        """A text-only transcription: one line per text line of the completion, no geometry. The raw
        completion is kept verbatim in ``extra["raw"]`` (``Transcription.text`` equals it, since lines
        are split on ``\\n`` and joined back), so post-processing can be decided later."""
        raw, finish = self.content(body)
        usage = body.get("usage") or {}
        return text_transcription(raw, self.step_info(backend, measurements={
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
            "finish_reason": finish}), finish_reason=finish)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.preset} ({self.model}@{(self.revision or '')[:8]})>"


def text_transcription(raw: str, model: StepInfo | None = None, finish_reason: str | None = None) -> Transcription:
    lines = [Line(id=f"l{i}", reading_order=i, text=t) for i, t in enumerate(raw.split("\n"))]
    return Transcription(lines=lines, steps=[model] if model else [],
                         source=Source(kind="produced", format="text"),
                         extra={"raw": raw, "finish_reason": finish_reason})


def data_url(mime: str, b64: str) -> dict:
    """An ``image_url`` content part."""
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


#: zlib's level for the PNGs a request sends: lossless at any level (the server decodes the same pixels); 1 encodes a
#: 2,048-px page 4.3 times faster than Pillow's default 6 for about 10 % more bytes (NOTES.md, 2026-11-12)
PNG_LEVEL = 1


def png_encode(img) -> bytes:
    """A Pillow image as PNG (``PNG_LEVEL``)."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=PNG_LEVEL)
    return buf.getvalue()


def png_bytes(img) -> str:
    """Base64 PNG of a Pillow image (``PNG_LEVEL``)."""
    return base64.b64encode(png_encode(img)).decode()


def png_longest(image: bytes, longest: int) -> tuple[str, tuple[int, int]]:
    """RGB, longest side forced to exactly ``longest`` px (up or down, LANCZOS), base64 PNG; and the size."""
    from PIL import Image

    from ..images.pixels import rgb_image

    img = rgb_image(image)
    w, h = img.size
    if max(w, h) != longest:
        scale = longest / max(w, h)
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    return png_bytes(img), img.size


# ------------------------------------------------------------------------------------------------ registry

#: adapter name -> ``module:Class`` (modules import lazily)
ADAPTERS = {
    "chandra-ocr": "chandra_ocr2:ChandraOCRAdapter",
    "deepseek-ocr": "deepseek_ocr:DeepSeekOCRAdapter",
    "dots": "dots:DotsAdapter",
    "glm-ocr": "glm_ocr:GLMOCRAdapter",
    "lighton-ocr-2": "lighton_ocr2:LightOnOCR2Adapter",
    "lighton-ocr-3": "lighton_ocr3:LightOnOCR3Adapter",
    "minicpm-ocr": "minicpm_ocr:MiniCPMOCRAdapter",
    "nemotron-parse": "nemotron_parse35:NemotronParseAdapter",
    "olmocr": "olmocr2:OlmOCRAdapter",
    "ovis-ocr": "ovis_ocr:OvisOCRAdapter",
    "paddleocr-vl": "paddleocr_vl:PaddleOCRVLAdapter",
    "qianfan-ocr": "qianfan_ocr:QianfanOCRAdapter",
    "qwen3.5": "qwen35:Qwen35Adapter",
    "smoldocling": "smoldocling:SmolDoclingAdapter",
    "unlimited-ocr": "unlimited_ocr:UnlimitedOCRAdapter",
    "unlimited-ocr-2": "unlimited_ocr:UnlimitedOCR2Adapter",
}


def adapter(name: str) -> type[ChatAdapter]:
    """The adapter class registered under ``name``."""
    from importlib import import_module

    if name not in ADAPTERS:
        raise CatalogError(f"unknown chat adapter {name!r}; known: {sorted(ADAPTERS)}")
    module, _, cls = ADAPTERS[name].partition(":")
    return getattr(import_module(f"{__name__}.{module}"), cls)


def adapters() -> dict[str, type[ChatAdapter]]:
    return {name: adapter(name) for name in ADAPTERS}


def chat_presets(catalog=None) -> dict[str, str]:
    """Chat preset ids -> the model's Hugging Face id."""
    from ..catalog.registry import catalog as installed

    c = catalog or installed()
    return {pid: c.model(p.model.id).source.ref for pid, (_, p) in sorted(c.presets.items())
            if p.engine == ENGINE and p.model is not None}


def preset_ref(ref: str, catalog=None, prefer: str = "page") -> str:
    """``ref`` as a preset ref: a preset id[@edition] as it is; a Hugging Face id becomes one of that model's
    presets, the first in id order with unit ``prefer`` (``page``, or ``region`` for region reading), else
    the first in id order."""
    from ..catalog.registry import catalog as installed

    c = catalog or installed()
    if ref.split("@", 1)[0] in c.presets:
        return ref
    ids = [pid for pid, repo in chat_presets(c).items() if repo == ref]
    if not ids:
        raise CatalogError(f"no chat preset for {ref!r}; chat presets: {sorted(chat_presets(c))}")
    return sorted(ids, key=lambda pid: (c.preset(pid).capabilities.unit != prefer, pid))[0]


def chat_model(ref: str, served_name: str | None = None, catalog=None, prefer: str = "page",
               overrides: dict[str, Any] | None = None) -> ChatAdapter:
    """The configured adapter for a chat preset: ``chat_model("lightonocr-2-1b")``, ``chat_model("dots-ocr@1")``,
    or by Hugging Face id, ``chat_model("lightonai/LightOnOCR-2-1B")`` (its page preset; ``prefer="region"``:
    its region preset). What it reads (``unit``) is the preset's capability. ``overrides``: ``ChatAdapter.Options``
    over the preset's settings, e.g. ``{"repair_max_tokens": 8192}``."""
    from ..catalog.registry import catalog as installed

    c = catalog or installed()
    r = c.resolve(preset_ref(ref, c, prefer))
    content = r.content
    engine = content.get("engine")
    if engine != ENGINE:
        raise CatalogError(f"preset {r.ref} is not a chat preset (engine {engine!r}, not {ENGINE})")
    options = dict(content.get("options") or {})
    m = c.model(content["model"]["id"])
    draft = None
    serve = dict(content.get("serve") or {})
    if serve.get("draft"):
        d = dict(serve["draft"])
        dm = c.model(d["model"])
        dm.pin(d["revision"])                   # the draft's revision must be pinned in its model entry
        draft = {"repo": dm.source.ref, "revision": d["revision"], "speculative": d.get("speculative") or {}}
    preset = ChatPreset(ref=r.ref, sha256=r.sha256, repo=m.source.ref, revision=content["model"]["revision"],
                        unit=c.preset(r.id).capabilities.unit or "page", options=options, settings=dict(content.get("settings") or {}),
                        serve=dict(content.get("serve") or {}), draft=draft)
    return adapter(options["adapter"])(preset, served_name=served_name).apply_overrides(overrides)


__all__ = ["ADAPTERS", "ChatAdapter", "ChatPreset", "ENGINE", "REPAIR_DEFAULTS", "adapter", "adapters", "chat_model", "chat_presets",
           "png_longest", "preset_ref", "text_transcription"]
