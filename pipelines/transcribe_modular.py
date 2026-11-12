# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray and the ray command (a Job leaves it out); nvImageCodec to decode page images on NVIDIA
#     # GPUs, used where the machine has one (its wheels install anywhere)
#     "linecaster[ray,nvimgcodec]",
#     # PaddleX's layout, line, recognition, table and formula engines (it brings the OpenCV stub)
#     "linecaster-paddlex",
#     # Tesseract's line recognizer
#     "linecaster-tesseract",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# linecaster-paddlex = { path = "../engines/paddlex", editable = true }
# linecaster-tesseract = { path = "../engines/tesseract", editable = true }
# ///
"""The modular pipeline (``transcribe_modular.v1``): its blocks, options and slots are the pipeline shape
``linecaster.pipelines.transcribe_modular``; this script gives it its environment. ``--help`` lists the options."""
from linecaster.pipelines import transcribe_modular as shape
from linecaster.runtime import run

if __name__ == "__main__":
    run.main(__file__, shape.__doc__, shape.options, shape.models, shape.pipeline, shape.PIPELINE, shape.SLOTS)
