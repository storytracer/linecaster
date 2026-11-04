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
# pybookget = { url = "https://github.com/storytracer/pybookget/archive/dd0ce49bd835be78fbbca4dd0ba470033454efad.tar.gz" }
# ///
r"""The harvest stage: page images from IIIF manifests (or from http(s) image URLs in Parquet), downloaded once
into item folders, with page rows that keep where each image came from. No engine or GPU is needed; the
recognition stage then reads the rows (or the image folder) without waiting on the libraries' servers.

    uv run pipelines/harvest.py --manifests manifests.txt OUT --tasks 16 --workers 4 --rate-limit 5/1
    uv run pipelines/chain.py --rows OUT/rows OUT2 --recipe ...                 # keeps the IIIF metadata
    uv run pipelines/chain.py OUT/images OUT2 --item-from-parent --recipe ...   # or the plain folder

Images in OUT/images/<item>/<page>.<ext> as the server sent them; page rows in OUT/rows/<rank>.jsonl.gz
(``image.uri`` the copy, ``image.extra.source_uri`` and ``metadata.iiif`` the source). Rate limits hold per
task: the servers see up to --workers times --rate-limit. A task that fails runs again whole (datatrove's
resume is per task), so keep tasks small. ``linecaster.run`` has the options every pipeline shares.
"""
from linecaster import run
from linecaster.blocks.writers import ImageFilesWriter


def options(ap):
    pass


def models(a) -> list[dict]:
    return []


def pipeline(a, script: str) -> list:
    if a.images or a.rows:
        raise SystemExit("harvest.py downloads: give --manifests or --parquet (with http(s) image URLs)")
    return [
        run.reader(a),
        ImageFilesWriter(f"{a.out.rstrip('/')}/images"),
        run.rows(a),
    ]


if __name__ == "__main__":
    run.main(__file__, __doc__, options, models, pipeline)
