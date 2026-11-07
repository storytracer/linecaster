# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray (HF Jobs leave it out)
#     "linecaster[ray,pybookget]",
#     # manifests (IIIF, METS) and http(s) images (--manifests); direct, so its source applies
#     "pybookget",
#     "linecaster-indra",
#     "linecaster-services",
#     "linecaster-surya",
#     # s3:// image folders (e.g. BHL's public bucket: FSSPEC_S3_ANON=true)
#     "s3fs",
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
# # surya-ocr 0.23.0 declares pillow<11, and linecaster needs Pillow>=11: the shared pin wins; torch stays the
# # build every other script has (surya-ocr would resolve the newest) (NOTES.md: the four board models)
# override-dependencies = [
#     "pillow==12.3.0",
#     "torch==2.14.0",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# pybookget = { url = "https://github.com/storytracer/pybookget/archive/91d39e4a56fb7bb3c1d5737fc66f824ab0dd3c9e.tar.gz" }
# linecaster-indra = { path = "../engines/indra", editable = true }
# linecaster-services = { path = "../engines/services", editable = true }
# linecaster-surya = { path = "../engines/surya", editable = true }
# ///
"""A page engine reads the whole page (``PageRecognizer`` on its engine): a vendor's package in the pipeline's process
(Indra OCR), a vendor's package attached to a vLLM server (Surya OCR), or a client of a vendor's page pipeline behind
its own HTTP API (Falcon-OCR, OXR). Each task starts the service the preset names (``ServiceServer``, last in the
pipeline: ``vllm serve`` on the pinned checkpoint, or the vendor image's entrypoint) unless --recognition-endpoint
names a running one. Page records in OUT/pages; the engine's raw output is in each page's transcription.

    uv run pipelines/transcribe_page.py IMAGES OUT --recognition indra-ocr --tasks 8 --workers 8   # CPU, in-process
    uv run pipelines/transcribe_page.py IMAGES OUT --recognition surya-ocr-2.5        # needs `vllm` (0.25.1) on PATH
    uv run pipelines/transcribe_page.py IMAGES OUT --recognition falcon-ocr           # inside the vendor's image
    uv run pipelines/transcribe_page.py IMAGES OUT --recognition oxr-1.0 --recognition-endpoint http://127.0.0.1:8000

--recognition takes a page engine's preset (``linecaster models``; ``id`` or ``id@edition``); chat presets run in
``pipelines/transcribe_vlm.py``. A vendor's service runs inside the vendor's image (the preset's ``serve.image``):
the pipeline runs there too, in its own uv environment, and the service in the image's own environments
(``ServiceServer`` leaves the pipeline's out of its environment). Its entrypoint listens on the image's ports, so
one task per machine starts it; more tasks share one service with --recognition-endpoint. On HF Jobs the Job's
image is the preset's ``serve.image`` unless --image is given; it needs uv (the vLLM and OXR images have it, the
Falcon-OCR image does not).
"""
from linecaster.blocks.recognition.chat import PageRecognizer
from linecaster.blocks.servers.service import ServiceServer
from linecaster.catalog.registry import catalog
from linecaster.errors import PipelineConfigError
from linecaster.runtime import run


def options(ap):
    ap.add_argument("--recognition", help="a page engine's preset (id[@edition]) (needed)")
    ap.add_argument("--recognition-endpoint", help="a running service for the engine (its base URL; vLLM's .../v1)")
    ap.add_argument("--boot-timeout", type=int, default=1800, help="seconds the service may take to start")


def preset(a):
    """The page engine's preset, checked: a recognition preset that reads whole pages and is no chat preset."""
    if not a.recognition:
        raise PipelineConfigError("page: pick --recognition (`linecaster models` lists the presets)")
    p = catalog().preset(a.recognition.partition("@")[0])
    if p.engine == "chat.v1":
        raise PipelineConfigError(f"page: {a.recognition} is a chat preset: run it with pipelines/transcribe_vlm.py")
    if not p.page_preset:
        raise PipelineConfigError(f"page: {a.recognition} does not read whole pages ({p.step}, unit "
                                  f"{p.capabilities.unit})")
    return p


def models(a) -> list[dict]:
    if not a.recognition:
        return []
    m = {"name": "recognition", "preset": a.recognition}
    if a.recognition_endpoint:
        m["overrides"] = {"endpoint": a.recognition_endpoint}
    return [m]


def pipeline(a, script: str):
    p = preset(a)
    b, servers = run.engines(a, models(a), script)
    steps = [run.reader(a), PageRecognizer(b["recognition"]), run.pages(a)]
    if p.serve is not None and not a.recognition_endpoint:
        # last: the service starts before the engine loads (blocks warm up as the stream reaches them, the last first)
        servers.append(ServiceServer(a.recognition, boot_timeout=a.boot_timeout))
    return steps + servers, {"image": p.serve.image if p.serve is not None else None, "engines": True}


#: what a recipe for this pipeline names (``linecaster.catalog.schema.RecipeDoc.pipeline``) and its slots
PIPELINE = "transcribe_page.v1"
SLOTS = {"recognition": "recognition"}

if __name__ == "__main__":
    run.main(__file__, __doc__, options, models, pipeline, PIPELINE, SLOTS)
