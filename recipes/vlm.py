# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray (HF Jobs leave it out)
#     "linecaster[ray]",
#     "linecaster-paddlex",
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
# linecaster-paddlex = { path = "../backends/paddlex", editable = true }
# opencv-contrib-python = { path = "../stubs/opencv-contrib-python" }
# ///
"""A vision-language model reads the page: the whole page (``ChatPageStep``) or, with --regions, each region
PP-DocLayoutV3 finds (``ChatRegionStep``). Each task starts vLLM or SGLang for the model itself
(``ServeChatModel``, last in the pipeline) unless --vlm-endpoint names a running server; with --regions
it also serves the layout model (``--backend``, ``--endpoint`` as for any engine model). Page rows in
OUT/rows; the model's raw answer is in each page's transcription.

    uv run recipes/vlm.py IMAGES OUT --vlm rednote-hilab/dots.ocr              # needs `vllm` on PATH
    uv run recipes/vlm.py IMAGES OUT --vlm-endpoint http://127.0.0.1:8000/v1   # a running server
    uv run recipes/vlm.py IMAGES OUT --vlm openbmb/MiniCPM-OCR-1.0 --regions
    uv run recipes/vlm.py IMAGES OUT --on hf-jobs --commit <sha> --vlm baidu/Unlimited-OCR-2

On HF Jobs the server runs in the Job's image: ``vllm/vllm-openai:v0.26.0`` (the BHL board's vLLM) unless
IMAGES names another for the model or --image is given. It has ``uv``, Python 3.12 and ``vllm`` on PATH,
so the pipeline runs in the uv environment the executor builds (linecaster alone for page models;
with --regions also linecaster-paddlex for the layout model), and ``ServeChatModel`` starts the image's
own server. SGLang specs and --regions start it outside that environment (``outside_venv``), so neither
the image's Python nor its CUDA libraries see the pipeline's packages. vLLM takes
--gpu-memory-utilization of the GPU (0.8, the board's value; SGLang: the spec's own share); with
--regions the layout server loads into the rest after vLLM's memory profiling.
"""
from linecaster import run
from linecaster.backends import Served
from linecaster.blocks.chat import ChatPageStep, ChatRegionStep
from linecaster.blocks.models import LayoutStep
from linecaster.blocks.serve import ServeChatModel
from linecaster.models import chat_model

#: the Jobs image a model was validated with, where it is not vllm/vllm-openai:v0.26.0
IMAGES = {
    "openbmb/MiniCPM-OCR-1.0": "cr.hf.co/davanstrien/minicpm-ocr:1.0-vllm-5d35ce3",
    "baidu/Unlimited-OCR-2": "lmsysorg/sglang:v0.5.20-cu130",
    "nvidia/Nemotron-3.5-Parse": "vllm/vllm-openai:v0.26.0@sha256:770fe65b2c73ee74a5c42165cf3433de4048cc2cd9c57a937ca4e35aba5aa87b",
}
VLLM_IMAGE = "vllm/vllm-openai:v0.26.0"
VLM_PORT = 8000


def options(ap):
    ap.add_argument("--vlm", default="lightonai/LightOnOCR-2-1B", help="the model's Hugging Face id")
    ap.add_argument("--regions", action="store_true", help="layout first, then the model on each region")
    ap.add_argument("--layout-model", default="PP-DocLayoutV3")
    ap.add_argument("--vlm-endpoint", help="a running OpenAI-compatible server for the model")
    ap.add_argument("--gpu-memory-utilization", type=float, default=None)
    ap.add_argument("--no-speculative", action="store_true", help="plain decoding where the spec has a draft")
    ap.add_argument("--window", type=int, default=48, help="requests in flight at the model's server")
    ap.add_argument("--initial-window", type=int, default=8)
    ap.add_argument("--layout-window", type=int, default=16, help="pages in flight at the layout server")
    ap.add_argument("--read-timeout", type=float, default=1800.0, help="seconds per request")


def models(a) -> list[dict]:
    return [{"name": "layout", "spec": "linecaster_paddlex:PaddleLayoutModel",
             "kwargs": {"model_name": a.layout_model}}] if a.regions else []


def pipeline(a, script: str):
    spec = chat_model(a.vlm)
    sglang = spec.server == "sglang"
    vlm = Served(a.vlm_endpoint or f"http://127.0.0.1:{VLM_PORT}/v1", model=spec.served_name, max_window=a.window,
                 initial_window=a.initial_window, read_timeout=a.read_timeout)
    steps = [run.reader(a)]
    servers = []
    if a.regions:
        b, servers = run.engines(a, models(a), script, a.layout_window)
        steps += [LayoutStep(b["layout"]), ChatRegionStep(spec, vlm)]
    else:
        steps += [ChatPageStep(spec, vlm)]
    if not a.vlm_endpoint:
        draft = getattr(spec, "draft_model", None)
        extra = [] if a.no_speculative or not draft else spec.speculative_args(draft, spec.draft_revision)
        gmu = a.gpu_memory_utilization if a.gpu_memory_utilization is not None or sglang else 0.8
        # last: boots first, so vLLM's memory profiling is done before a layout server loads
        servers.append(ServeChatModel(spec, port=VLM_PORT, gpu_memory_utilization=gmu, extra_args=extra,
                                      outside_venv=sglang or a.regions))
    return steps + [run.rows(a)] + servers, {"image": IMAGES.get(a.vlm, VLLM_IMAGE), "engines": a.regions}


if __name__ == "__main__":
    run.main(__file__, __doc__, options, models, pipeline)
