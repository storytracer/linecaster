# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray and the ray command (a Job leaves it out); Omni Parse Bench: its Markdown converter and grading
#     "linecaster[ray,omniparsebench]",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# ///
"""A run graded by Omni Parse Bench (``omniparsebench.v1``): its blocks, options and slots are the pipeline shape
``linecaster.pipelines.omniparsebench``; this script gives it its environment. ``--help`` lists the options."""
from linecaster.pipelines import omniparsebench as shape
from linecaster.runtime import run

if __name__ == "__main__":
    run.main(__file__, shape.__doc__, shape.options, shape.models, shape.pipeline, shape.PIPELINE, shape.SLOTS)
