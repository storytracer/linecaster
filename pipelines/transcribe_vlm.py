# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray (HF Jobs leave it out)
#     "linecaster[ray,pybookget]",
#     # manifests (IIIF, METS) and http(s) images (--manifests); direct, so its source applies
#     "pybookget",
#     "linecaster-paddlex",
#     # s3:// image folders (e.g. BHL's public bucket: FSSPEC_S3_ANON=true)
#     "s3fs",
#     # PaddleX pins OpenCV's GUI build; this stub swaps in the headless build of the same version
#     "opencv-contrib-python",
# ]
#
# [tool.uv]
# # the versions squiddleocr's goldens were recorded with (numerics: recognition, ONNX Runtime, CUDA, decoding);
# # the same list in every script (tests/test_scripts.py)
# constraint-dependencies = [
#     "lightning==2.6.6",
#     "onnxruntime-gpu==1.29.0",
#     "pillow==12.3.0",
#     "transformers==5.12.1",
#     "tokenizers==0.22.2",
#     "nvidia-cublas==13.1.1.3",
#     "nvidia-cuda-nvrtc==13.0.88",
#     "nvidia-cuda-runtime==13.0.96",
#     "nvidia-cudnn-cu13==9.24.0.43",
#     "nvidia-cufft==12.0.0.61",
#     "nvidia-curand==10.4.0.35",
#     "scipy==1.15.3",
#     "scikit-image==0.25.2",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# pybookget = { url = "https://github.com/storytracer/pybookget/archive/91d39e4a56fb7bb3c1d5737fc66f824ab0dd3c9e.tar.gz" }
# linecaster-paddlex = { path = "../engines/paddlex", editable = true }
# opencv-contrib-python = { path = "../stubs/opencv-contrib-python" }
# ///
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
from linecaster.adapters import preset_ref
from linecaster.backends import Chat
from linecaster.blocks.layout.detector import LayoutDetector
from linecaster.blocks.recognition.chat import PageRecognizer, RegionRecognizer
from linecaster.blocks.servers.serve import ChatModelServer
from linecaster.errors import PipelineConfigError
from linecaster.runtime import run

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

if __name__ == "__main__":
    run.main(__file__, __doc__, options, models, pipeline, PIPELINE, SLOTS)
