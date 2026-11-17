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
"""The item stage (``bind.v1``): its components, options and slots are the pipeline template ``linecaster.templates.bind``;
this script gives it its environment. ``--help`` lists the options."""
from linecaster.templates import bind as template
from linecaster.execution import run

if __name__ == "__main__":
    run.main(__file__, template.__doc__, template.options, template.models, template.pipeline, template.PIPELINE, template.SLOTS)
