# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray and the ray command (a Job leaves it out); nvImageCodec to decode page images on NVIDIA
#     # GPUs, used where the machine has one (its wheels install anywhere)
#     "linecaster[ray,nvimgcodec]",
#     # the recipe's engine packages: kraken's line recognizer (it brings the kraken fork and torch 2.14), PaddleX's
#     # layout, line, table and formula engines (it brings the OpenCV stub)
#     "linecaster-kraken",
#     "linecaster-paddlex",
# ]
#
# [tool.uv.sources]
# # linecaster's main branch on GitHub, so the script runs from its URL as well as from a checkout
# linecaster = { git = "https://github.com/storytracer/linecaster", branch = "main" }
# linecaster-kraken = { git = "https://github.com/storytracer/linecaster", branch = "main", subdirectory = "engines/kraken" }
# linecaster-paddlex = { git = "https://github.com/storytracer/linecaster", branch = "main", subdirectory = "engines/paddlex" }
# ///
"""The recipe ``squiddle`` (its presets and editions are the catalog's): this script gives it its environment.
``--help`` lists the options; ``uv run recipes/squiddle.py IMAGES OUT``."""
from linecaster.runtime import run

if __name__ == "__main__":
    run.recipe(__file__, "squiddle")
