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
# pybookget = { url = "https://github.com/storytracer/pybookget/archive/45814da404b17c0289bd9e20f95f72cd5a663e39.tar.gz" }
# linecaster-indra = { path = "../engines/indra", editable = true }
# linecaster-services = { path = "../engines/services", editable = true }
# linecaster-surya = { path = "../engines/surya", editable = true }
# ///
"""The page-engine pipeline (``transcribe_page.v1``): its blocks, options and slots are the pipeline shape
``linecaster.pipelines.transcribe_page``; this script gives it its environment. ``--help`` lists the options."""
from linecaster.pipelines import transcribe_page as shape
from linecaster.runtime import run

if __name__ == "__main__":
    run.main(__file__, shape.__doc__, shape.options, shape.models, shape.pipeline, shape.PIPELINE, shape.SLOTS)
