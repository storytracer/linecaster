# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray; the MediaWiki importer (linecaster-mediawiki: wikitextprocessor, pinned to a commit)
#     "linecaster[ray]",
#     "linecaster-mediawiki",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# linecaster-mediawiki = { path = "../engines/mediawiki", editable = true }
# ///
"""Importing transcriptions (``import_transcriptions.v1``): its components, options and slots are the pipeline shape
``linecaster.templates.import_transcriptions``; this script gives it its environment. ``--help`` lists the options."""
from linecaster.templates import import_transcriptions as shape
from linecaster.execution import run

if __name__ == "__main__":
    run.main(__file__, shape.__doc__, shape.options, shape.models, shape.pipeline, shape.PIPELINE, shape.SLOTS)
