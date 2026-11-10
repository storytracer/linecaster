# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray and the ray command (a Job leaves it out)
#     "linecaster[ray]",
#     # the layout model for --layout (PaddleX; it brings the OpenCV stub)
#     "linecaster-paddlex",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# linecaster-paddlex = { path = "../engines/paddlex", editable = true }
# ///
"""The VLM pipeline (``transcribe_vlm.v1``): its blocks, options and slots are the pipeline shape
``linecaster.pipelines.transcribe_vlm``; this script gives it its environment. ``--help`` lists the options."""
from linecaster.pipelines import transcribe_vlm as shape
from linecaster.runtime import run

if __name__ == "__main__":
    run.main(__file__, shape.__doc__, shape.options, shape.models, shape.pipeline, shape.PIPELINE, shape.SLOTS)
