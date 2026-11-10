# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray (HF Jobs leave it out)
#     "linecaster[ray,pybookget]",
#     # manifests (IIIF, METS) and http(s) images (--manifests); direct, so its source applies
#     "pybookget",
#     "linecaster-kraken",
#     "linecaster-paddlex",
#     "linecaster-tesseract",
#     # direct, so the fork in [tool.uv.sources] applies (sources only apply to a script's own dependencies)
#     "kraken",
#     # s3:// image folders (e.g. BHL's public bucket: FSSPEC_S3_ANON=true)
#     "s3fs",
#     # PaddleX pins OpenCV's GUI build; this stub swaps in the headless build of the same version
#     "opencv-contrib-python",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# pybookget = { url = "https://github.com/storytracer/pybookget/archive/45814da404b17c0289bd9e20f95f72cd5a663e39.tar.gz" }
# linecaster-kraken = { path = "../engines/kraken", editable = true }
# linecaster-paddlex = { path = "../engines/paddlex", editable = true }
# linecaster-tesseract = { path = "../engines/tesseract", editable = true }
# # kraken with the PP-OCRv6 code from our fork: upstream main (bb487219) plus the inference precision fix and the
# # line prefetch (storytracer/linecaster#1)
# kraken = { git = "https://github.com/storytracer/kraken", rev = "48eecb78" }
# opencv-contrib-python = { path = "../stubs/opencv-contrib-python" }
# ///
"""The modular pipeline (``transcribe_modular.v1``): its blocks, options and slots are the pipeline shape
``linecaster.pipelines.transcribe_modular``; this script gives it its environment. ``--help`` lists the options."""
from linecaster.pipelines import transcribe_modular as shape
from linecaster.runtime import run

if __name__ == "__main__":
    run.main(__file__, shape.__doc__, shape.options, shape.models, shape.pipeline, shape.PIPELINE, shape.SLOTS)
