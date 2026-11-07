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
# pybookget = { url = "https://github.com/storytracer/pybookget/archive/bf8eee106edfeef1c7680a6338135960497195e1.tar.gz" }
# ///
r"""The harvest stage: items' page images (and, with --existing-ocr, the library's own OCR) from their manifests
(IIIF or METS; a folder, a list of links, or item tables with --manifest-key), or from http(s) image URLs in a page
table (--parquet), downloaded once into item folders, with page records that keep where everything came from. No
engine or GPU is needed; the transcribe stage then reads the page records without waiting on the libraries' servers.

    uv run pipelines/harvest.py --manifests items.parquet --manifest-key manifest_url --item-key item_id OUT \
        --rate-limit 5/1 --existing-ocr
    uv run pipelines/harvest.py --parquet pages.parquet --item-key book --sequence-key page --image-key url OUT \
        --rate-limit 150/60 --rate-limit 3/1
    uv run pipelines/harvest.py ... SMOKE --rate-limit 150/60 --rate-limit 3/1 --max-pages 2000     # a smoke test
    uv run pipelines/transcribe_modular.py --pages OUT/pages OUT2 --recipe ...                 # keeps the metadata
    uv run pipelines/transcribe_modular.py OUT/images OUT2 --item-from-parent --recipe ...   # or the plain folder

OUT/images/<item>/<page>.<ext> as the server sent them; with --existing-ocr OUT/ocr/<item>/<page>.xml|.html; the
manifests as fetched in OUT/manifests/<item>.json|.xml; page records in OUT/pages/<rank>.jsonl.gz (``image.uri`` the
copy, ``image.extra.source_uri`` the source, ``metadata.manifest`` the item's and page's manifest data, the
transcription ``ocr_original`` with the existing OCR).

Nothing needs sizing: --rate-limit holds per worker, and with it one worker runs the tasks (the run states what a
server sees before it starts). The input is divided into tasks of
about 1,000 pages (a --parquet page table by rows, whatever its files; --manifests about 5 items each), so a rerun into
the same OUT repeats at most the task each worker was in (datatrove's resume is per task). With rate limits one
worker runs the tasks one after the other: its requests ahead (manifests' pages and http(s) images alike) grow until
the rate limits are kept busy, and the limits hold across its tasks. --tasks and --workers still override; with
--workers N a server sees N times --rate-limit, so give each worker its part. --max-pages N runs the first N pages of
the input in
the same automatic tasks, a smoke test of the real setup (--limit counts per task, as in datatrove).
``linecaster.runtime.run`` has the options every pipeline shares.
"""
from linecaster.blocks.conversion import TranscriptionConverter
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
    ocr = bool(a.manifests and a.existing_ocr)
    return [
        run.reader(a, manifest_folder=f"{out}/manifests" if a.manifests else None),
        # the library's OCR file (a document media) read into ocr_original
        *([TranscriptionConverter()] if ocr else []),
        ImageFilesWriter(f"{out}/images", ocr_folder=f"{out}/ocr" if ocr else None),
        run.pages(a),
    ]


#: the pipeline's id (its docs page; ``launch.py`` finds scripts by it); no slots, so no recipes
PIPELINE = "harvest.v1"

if __name__ == "__main__":
    run.main(__file__, __doc__, options, models, pipeline)
