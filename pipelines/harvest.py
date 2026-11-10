# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray and the ray command (a Job leaves it out), pybookget for the manifests and http(s) files it
#     # fetches
#     "linecaster[ray,pybookget]",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# ///
"""The harvest stage (``harvest.v1``): its blocks and options are the pipeline shape
``linecaster.pipelines.harvest``; this script gives it its environment. ``--help`` lists the options."""
from linecaster.pipelines import harvest as shape
from linecaster.runtime import run

if __name__ == "__main__":
    run.main(__file__, shape.__doc__, shape.options, shape.models, shape.pipeline)
