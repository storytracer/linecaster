# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray and the ray command (a Job leaves it out); nvImageCodec for NVIDIA GPUs, used where the
#     # machine has one (its wheels install anywhere)
#     "linecaster[ray,nvimgcodec]",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# ///
"""Image conversion (``convert.v1``): its blocks, options and slots are the pipeline shape
``linecaster.pipelines.convert``; this script gives it its environment. ``--help`` lists the options."""
from linecaster.pipelines import convert as shape
from linecaster.runtime import run

if __name__ == "__main__":
    run.main(__file__, shape.__doc__, shape.options, shape.models, shape.pipeline, shape.PIPELINE, shape.SLOTS)
