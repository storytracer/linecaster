# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray and the ray command (a Job leaves it out)
#     "linecaster[ray]",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# ///
"""The harvest stage (``harvest.v1``): its components and options are the pipeline shape
``linecaster.templates.harvest``; this script gives it its environment. ``--help`` lists the options."""
from linecaster.templates import harvest as shape
from linecaster.execution import run

if __name__ == "__main__":
    run.main(__file__, shape.__doc__, shape.options, shape.models, shape.pipeline)
