# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray and the ray command (a Job leaves it out); the recipe's engines are linecaster's own
#     "linecaster[ray]",
# ]
#
# [tool.uv.sources]
# # linecaster's main branch on GitHub, so the script runs from its URL as well as from a checkout
# linecaster = { git = "https://github.com/storytracer/linecaster", branch = "main" }
# ///
"""The recipe ``item-texts`` (its presets and editions are the catalog's): this script gives it its environment.
``--help`` lists the options; ``uv run recipes/item-texts.py PAGES OUT``."""
from linecaster.runtime import run

if __name__ == "__main__":
    run.recipe(__file__, "item-texts")
