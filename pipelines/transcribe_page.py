# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray (HF Jobs leave it out)
#     "linecaster[ray,pybookget]",
#     # manifests (IIIF, METS) and http(s) images (--manifests); direct, so its source applies
#     "pybookget",
#     "linecaster-indra",
#     "linecaster-services",
#     "linecaster-surya",
#     # s3:// image folders (e.g. BHL's public bucket: FSSPEC_S3_ANON=true)
#     "s3fs",
# ]
#
# [tool.uv]
# # surya-ocr 0.23.0 declares pillow<11, and linecaster needs Pillow>=11: the override wins; torch stays the
# # build every other script has (surya-ocr would resolve the newest) (NOTES.md: the four board models)
# override-dependencies = [
#     "pillow==12.3.0",
#     "torch==2.14.0",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# pybookget = { url = "https://github.com/storytracer/pybookget/archive/45814da404b17c0289bd9e20f95f72cd5a663e39.tar.gz" }
# linecaster-indra = { path = "../engines/indra", editable = true }
# linecaster-services = { path = "../engines/services", editable = true }
# linecaster-surya = { path = "../engines/surya", editable = true }
# ///
"""The page-engine pipeline (``transcribe_page.v1``): its blocks, options and slots are the pipeline shape
``linecaster.pipelines.transcribe_page``; this script gives it its environment. ``--help`` lists the options."""
from linecaster.pipelines import transcribe_page as shape
from linecaster.runtime import run

if __name__ == "__main__":
    run.main(__file__, shape.__doc__, shape.options, shape.models, shape.pipeline, shape.PIPELINE, shape.SLOTS)
