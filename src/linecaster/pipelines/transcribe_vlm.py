"""A vision-language model reads the page: the whole page (``PageRecognizer``) or, with a --layout preset, each
region it finds (``RegionRecognizer``, a region preset), on the ``Chat`` backend. Each task starts vLLM or SGLang for the model itself
(``ChatModelServer``, last in the pipeline) unless --recognition-endpoint names a running server; with --layout it also
serves the layout model (``--backend``, ``--endpoint`` as for any engine). Page records in OUT/pages; the
model's raw answer is in each page's transcription.

    uv run pipelines/transcribe_vlm.py IMAGES OUT --recognition dots-ocr                     # needs `vllm` on PATH
    uv run pipelines/transcribe_vlm.py IMAGES OUT --recognition dots-ocr --recognition-endpoint http://127.0.0.1:8000/v1
    uv run pipelines/transcribe_vlm.py IMAGES OUT --layout pp-doclayoutv3 --recognition minicpm-ocr-1.0
    uv run pipelines/transcribe_vlm.py IMAGES OUT --on hf-jobs --commit <sha> --recognition unlimited-ocr-2

--recognition takes a chat preset of the catalog (``linecaster models``; ``id`` or ``id@edition``) or a Hugging Face
id (that model's page preset, with --layout its region preset where it has one). On HF Jobs the server runs
in the Job's image: the one the preset was validated with (its ``serve.image``) unless --image is given. It
has ``uv``, Python 3.12 and ``vllm`` on PATH, so the pipeline runs in the uv environment the executor builds
(linecaster alone for page presets; with --layout also linecaster-paddlex for the layout model), and
``ChatModelServer`` starts the image's own server. SGLang presets and region reading start it outside that
environment (``outside_venv``), so neither the image's Python nor its CUDA libraries see the pipeline's
packages. vLLM takes --gpu-memory-utilization of the GPU (0.8, the board's value; SGLang: the preset's own
share); with --layout the layout server loads into the rest after vLLM's memory profiling.
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


def models(a) -> list[dict]:
    return [{"name": "layout", "preset": a.layout}] if a.layout else []


def pipeline(a, script: str):
    if not a.recognition:
        raise PipelineConfigError("vlm: pick --recognition (`linecaster models` lists the presets)")
    regions = bool(a.layout)
    vlm = Chat(preset_ref(a.recognition, prefer="region" if regions else "page"),
               a.recognition_endpoint or f"http://127.0.0.1:{VLM_PORT}/v1", max_window=a.window,
               initial_window=a.initial_window, read_timeout=a.read_timeout)
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
        steps += [PageRecognizer(vlm)]
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
