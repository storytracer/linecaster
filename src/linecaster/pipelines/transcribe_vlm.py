r"""A vision-language model reads the page: the whole page (``PageRecognizer``) or, with a --layout preset, each
region it finds (``RegionRecognizer``, a region preset), on the ``Chat`` backend. Each task starts vLLM or SGLang for the model itself
(``ChatModelServer``, last in the pipeline) unless --recognition-endpoint names a running server; with --layout it also
serves the layout model (``--backend``, ``--endpoint`` as for any engine). Page records in OUT/pages; the
model's raw answer is in each page's transcription.

    uv run pipelines/transcribe_vlm.py IMAGES OUT --recognition dots-ocr                     # needs `vllm` on PATH
    uv run pipelines/transcribe_vlm.py IMAGES OUT --recognition dots-ocr --recognition-endpoint http://127.0.0.1:8000/v1
    uv run pipelines/transcribe_vlm.py IMAGES OUT --layout pp-doclayoutv3 --recognition minicpm-ocr-1.0
    uv run pipelines/transcribe_vlm.py IMAGES OUT --on hf-jobs --namespace NS --commit <sha> --recognition unlimited-ocr-2
    ... --set "recognition.repair_max_tokens=[8192, 12288]"   # repair passes (below); =0: off (on in lightonocr-3-0.8b@3)
    ... --set recognition.max_tokens=6000 --set recognition.temperature=0   # the sampling over the preset's
    ... --repetition-detection                                # vLLM ends a looping completion (below)
    ... --set recognition.repetition_detection.min_count=12   # one of its settings over the defaults
    uv run pipelines/transcribe_vlm.py OUT2 --pages OUT/pages --repair-only --recognition lightonocr-3-0.8b
                                                          # the repair pass over page records written before

--recognition takes a chat preset of the catalog (``linecaster models``; ``id`` or ``id@edition``) or a Hugging Face
id (that model's page preset, with --layout its region preset where it has one). On HF Jobs the server runs
in the Job's image: the one the preset was validated with (its ``serve.image``) unless --image is given. It
has ``uv``, Python 3.12 and ``vllm`` on PATH, so the pipeline runs in the uv environment the executor builds
(linecaster alone for page presets; with --layout also linecaster-paddlex for the layout model), and
``ChatModelServer`` starts the image's own server. SGLang presets and region reading start it outside that
environment (``outside_venv``), so neither the image's Python nor its CUDA libraries see the pipeline's
packages. vLLM takes --gpu-memory-utilization of the GPU (0.8, linecaster's default; SGLang: the preset's own
share); with --layout the layout server loads into the rest after vLLM's memory profiling. The server listens on port
8000 in every run: two runs on one machine need a GPU each (``CUDA_VISIBLE_DEVICES``) and cannot both start their own
server; on a machine without a CUDA toolkit vLLM starts with ``VLLM_USE_FLASHINFER_SAMPLER=0`` (``ChatModelServer``).

--set STEP.OPTION=VALUE sets an option over the preset's: for --recognition the chat engine's ``max_tokens``,
``temperature``, ``top_p``, ``repair_max_tokens``, ``repair_temperature`` and ``repetition_detection``
(``linecaster.adapters.ChatAdapter``), for --layout the layout engine's options. They go into the run record and
change its ``pipeline_sha256``.

--repetition-detection (``--set recognition.repetition_detection=true``) turns on vLLM's repetition detection with
its defaults (patterns of 8 to 100 tokens repeated 16 times): a completion that loops ends early with
``finish_reason`` ``repetition`` (stat ``finish_repetition``) and is not repaired, instead of running to
``max_tokens`` and through the repair passes. Only presets served by vLLM 0.17.0 or later take it; it is refused for
the others, whose servers would ignore it.

The repair pass (``--set recognition.repair_max_tokens=N``, N larger than the preset's ``max_tokens``; page presets
only): a page whose completion stopped at ``max_tokens`` is sent again right away, the same image, prompt and
``top_p``, with ``max_tokens`` N (at most the served context minus the page's prompt) and temperature
``repair_temperature`` (0.1); with a list of rising caps (``[8192, 12288]``), each repair that stops at its cap is
sent again with the next. The page keeps the first completion that finished (``stop``), its first one otherwise, and
its transcription records every pass (``extra["passes"]``, ``extra["kept"]``). The procedure is the reference
script's (uv-scripts/ocr ``lighton-ocr3-saturate.py`` at e2b0aa5), which suggests 8192 for LightOnOCR-3;
``lightonocr-3-0.8b@3`` repairs at 8192 and then 12288 (twice and three times its 4096), since dense tables needed
up to about 9,000 tokens. A page that
stops at ``max_tokens`` is often a repetition loop, which a repair does not end, but a dense table can simply need
more tokens and then finishes; the repair adds the second requests' tokens to the run (NOTES.md has the trials). A
page whose prompt leaves no more room in the context than the first request had gets no repair (stat
``repair_skipped``); a run warns at the start when N plus a page's largest prompt exceeds the context. With --repair-only (and --pages, page records of an earlier run of
the same model) only the repair requests are sent: for the pages that stopped at ``max_tokens`` and have no repair
yet; every other page is written as it was read.
"""
from ..adapters import preset_ref
from ..backends import Chat
from ..blocks.layout.detector import LayoutDetector
from ..blocks.recognition.chat import PageRecognizer, RegionRecognizer
from ..blocks.servers.serve import ChatModelServer
from ..errors import PipelineConfigError
from ..runtime import run

VLM_PORT = 8000


def options(ap):
    ap.add_argument("--recognition", help="a chat preset (id[@edition]) or a model's Hugging Face id (needed)")
    ap.add_argument("--layout", help="a layout preset: the model then reads each region (a region preset)")
    ap.add_argument("--recognition-endpoint", help="a running OpenAI-compatible server for the model")
    ap.add_argument("--gpu-memory-utilization", type=float, default=None)
    ap.add_argument("--no-speculative", action="store_true", help="plain decoding where the spec has a draft")
    ap.add_argument("--window", type=int, default=48, help="requests in flight at the model's server")
    ap.add_argument("--initial-window", type=int, default=8)
    ap.add_argument("--layout-window", type=int, default=16, help="pages in flight at the layout server")
    ap.add_argument("--read-timeout", type=float, default=1800.0, help="seconds per request")
    ap.add_argument("--set", action="append", default=[], metavar="STEP.OPTION=VALUE",
                    help="an option over the preset's, e.g. 'recognition.repair_max_tokens=[8192, 12288]' (repair passes), "
                         "recognition.max_tokens, .temperature, .top_p, .repair_temperature, or a layout engine "
                         "option; repeatable")
    ap.add_argument("--repetition-detection", action="store_true",
                    help="vLLM ends a completion that loops (finish_reason repetition, not repaired): its repetition "
                         "detection with linecaster's defaults; --set recognition.repetition_detection.FIELD=N for "
                         "one of min_pattern_size, max_pattern_size, min_count")
    ap.add_argument("--repair-only", action="store_true",
                    help="with --pages: send only the repair pass (--set recognition.repair_max_tokens=N) for the "
                         "pages that stopped at max_tokens and have none yet; the others are written unchanged")


def sets(a) -> dict[str, dict]:
    """``--set`` by step: ``recognition`` (the chat engine's options) and, with --layout, ``layout``;
    --repetition-detection is ``recognition.repetition_detection=true`` unless --set gives it."""
    out = run.overrides(a.set, steps=["recognition", *(["layout"] if a.layout else [])])
    if getattr(a, "repetition_detection", False):
        rec = out.setdefault("recognition", {})
        if "repetition_detection" not in rec:
            rec["repetition_detection"] = True
    return out


def models(a) -> list[dict]:
    over = sets(a)
    return ([{"name": "layout", "preset": a.layout, **({"overrides": over["layout"]} if "layout" in over else {})}]
            if a.layout else [])


def pipeline(a, script: str):
    if not a.recognition:
        raise PipelineConfigError("vlm: pick --recognition (`linecaster models` lists the presets)")
    regions = bool(a.layout)
    if a.repair_only and (regions or not a.pages):
        raise PipelineConfigError("vlm: --repair-only reads page records (--pages OUT/pages) of whole pages, "
                                  "without --layout")
    vlm = Chat(preset_ref(a.recognition, prefer="region" if regions else "page"),
               a.recognition_endpoint or f"http://127.0.0.1:{VLM_PORT}/v1", max_window=a.window,
               initial_window=a.initial_window, read_timeout=a.read_timeout,
               overrides=sets(a).get("recognition"))
    spec = vlm.adapter
    if regions != (spec.unit == "region"):
        reads = "regions" if spec.unit == "region" else "whole pages"
        raise PipelineConfigError(f"vlm: {a.recognition} reads {reads}"
                                  + ("; pick --layout for it" if not regions else "; pick a region preset with --layout"))
    sglang = spec.server == "sglang"
    steps = [run.reader(a)]
    servers = []
    if regions:
        b, servers = run.engines(a, models(a), script, a.layout_window)
        steps += [LayoutDetector(b["layout"]), RegionRecognizer(vlm)]
    else:
        steps += [PageRecognizer(vlm, repair_only=a.repair_only)]
    if not a.recognition_endpoint:
        draft = getattr(spec, "draft_model", None)
        extra = [] if a.no_speculative or not draft else spec.speculative_args(draft, spec.draft_revision)
        gmu = a.gpu_memory_utilization if a.gpu_memory_utilization is not None or sglang else 0.8
        # last: boots first, so vLLM's memory profiling is done before a layout server loads
        servers.append(ChatModelServer(spec, port=VLM_PORT, gpu_memory_utilization=gmu, extra_args=extra,
                                      outside_venv=sglang or regions))
    return steps + [run.pages(a)] + servers, {"image": spec.job_image, "engines": regions}


#: what a recipe for this pipeline names (``linecaster.catalog.schema.RecipeDoc.pipeline``) and its slots
PIPELINE = "transcribe_vlm.v1"
SLOTS = {"recognition": "recognition", "layout": "layout"}
