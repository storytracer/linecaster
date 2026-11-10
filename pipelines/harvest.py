# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray (HF Jobs leave it out)
#     "linecaster[ray,pybookget]",
#     # direct, so their sources apply (sources only apply to a script's own dependencies)
#     "pybookget",
#     # s3:// output folders
#     "s3fs",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# pybookget = { url = "https://github.com/storytracer/pybookget/archive/45814da404b17c0289bd9e20f95f72cd5a663e39.tar.gz" }
# ///
"""The harvest stage (``harvest.v1``): its blocks and options are the pipeline shape
``linecaster.pipelines.harvest``; this script gives it its environment. ``--help`` lists the options."""
from linecaster.pipelines import harvest as shape
from linecaster.runtime import run

if __name__ == "__main__":
    run.main(__file__, shape.__doc__, shape.options, shape.models, shape.pipeline)
