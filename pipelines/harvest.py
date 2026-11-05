# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray (HF Jobs leave it out)
#     "linecaster[ray,pybookget]",
#     # direct, so its source applies (sources only apply to a script's own dependencies)
#     "pybookget",
#     # s3:// output folders
#     "s3fs",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# pybookget = { url = "https://github.com/storytracer/pybookget/archive/449bcc50b25aaa8d4ad4ea00bc78c9554e136af7.tar.gz" }
# ///
r"""The harvest stage: items' page images (and, with --existing-ocr, the library's own OCR) from their manifests
(IIIF or METS; a folder, a list of links, or item tables with --manifest-key), or from http(s) image URLs in a page
table (--parquet), downloaded once into item folders, with page records that keep where everything came from. No
engine or GPU is needed; the transcribe stage then reads the page records without waiting on the libraries' servers.

    uv run pipelines/harvest.py --manifests items.parquet --manifest-key manifest_url --item-key item_id OUT \
        --tasks 16 --workers 4 --rate-limit 5/1 --existing-ocr
    uv run pipelines/transcribe_modular.py --pages OUT/pages OUT2 --recipe ...                 # keeps the metadata
    uv run pipelines/transcribe_modular.py OUT/images OUT2 --item-from-parent --recipe ...   # or the plain folder

OUT/images/<item>/<page>.<ext> as the server sent them; with --existing-ocr OUT/ocr/<item>/<page>.xml|.html; the
manifests as fetched in OUT/manifests/<item>.json|.xml; page records in OUT/pages/<rank>.jsonl.gz (``image.uri`` the
copy, ``image.extra.source_uri`` the source, ``metadata.manifest`` the item's and page's manifest data, the
transcription ``ocr_original`` with the existing OCR). Rate limits hold per task: the servers see up to --workers
times --rate-limit. A task that fails runs again whole (datatrove's resume is per task), so keep tasks small.
``linecaster.runtime.run`` has the options every pipeline shares.
"""
from linecaster.blocks.writers.images import ImageFilesWriter
from linecaster.errors import PipelineConfigError
from linecaster.runtime import run


def options(ap):
    pass


def models(a) -> list[dict]:
    return []


def pipeline(a, script: str) -> list:
    if a.images or a.pages:
        raise PipelineConfigError("harvest.py downloads: give --manifests or --parquet (with http(s) image URLs)")
    out = a.out.rstrip("/")
    return [
        run.reader(a, manifest_folder=f"{out}/manifests" if a.manifests else None),
        ImageFilesWriter(f"{out}/images", ocr_folder=f"{out}/ocr" if a.manifests and a.existing_ocr else None),
        run.pages(a),
    ]


#: the pipeline's id (its docs page; ``launch.py`` finds scripts by it); no slots, so no recipes
PIPELINE = "harvest.v1"

if __name__ == "__main__":
    run.main(__file__, __doc__, options, models, pipeline)
