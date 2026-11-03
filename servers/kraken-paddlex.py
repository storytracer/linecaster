# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "linecaster",
#     "linecaster-kraken",
#     "linecaster-paddlex",
#     # direct, so the fork in [tool.uv.sources] applies (sources only apply to a script's own dependencies)
#     "kraken",
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
# linecaster-kraken = { path = "../backends/kraken", editable = true }
# linecaster-paddlex = { path = "../backends/paddlex", editable = true }
# # kraken with the PP-OCRv6 code from our fork: upstream main (bb487219) plus the inference precision fix
# kraken = { git = "https://github.com/storytracer/kraken", rev = "3d235ee8" }
# opencv-contrib-python = { path = "../stubs/opencv-contrib-python" }
# ///
"""``linecaster serve`` with the kraken and PaddleX engines (the squiddle combination: layout, lines,
recognition, tables, formulas). The arguments are ``linecaster serve``'s:

    uv run servers/kraken-paddlex.py --config examples/squiddle_models.json --port 8100
"""
import sys

from linecaster.cli import main

if __name__ == "__main__":
    main(["serve", *sys.argv[1:]])
