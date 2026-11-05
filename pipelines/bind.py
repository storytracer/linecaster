# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray (HF Jobs leave it out)
#     "linecaster[ray]",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# ///
r"""The item stage (binding): one text per item (book, issue, manuscript) and text version, from the page records of a first
stage written in item shards (`--item-shards N`). Each task reads whole shard folders, so it sees every page of
its items; no engine or GPU is needed.

    uv run pipelines/transcribe_modular.py IMAGES OUT1 ... --tasks 4000 --item-shards 64
    uv run pipelines/bind.py OUT1/pages OUT2 --tasks 64
    ... --on hf-jobs --commit <sha> --flavor cpu-upgrade --tasks 64

Texts in OUT2/texts/<version>/<rank>.jsonl.gz; with --files also OUT2/files/<version>/<item>.txt|.md.
``linecaster.runtime.run`` has the options every pipeline shares (IMAGES is the first stage's page records folder here).
"""
from linecaster.blocks.binding.texts import ItemTexts
from linecaster.blocks.readers.records import PageRecordReader
from linecaster.blocks.writers.items import ItemTextWriter
from linecaster.runtime import run


def options(ap):
    ap.add_argument("--files", action="store_true", help="also one file per item and version: OUT/files/...")


def models(a) -> list[dict]:
    return []


def pipeline(a, script: str) -> list:
    out = a.out.rstrip("/")
    return [
        PageRecordReader(a.images, fetch_images=False, item_shards=True),
        ItemTexts(),
        *([ItemTextWriter(f"{out}/files", format="files")] if a.files else []),
        ItemTextWriter(f"{out}/texts"),
    ], {"engines": False}


#: the pipeline's id (its docs page; ``launch.py`` finds scripts by it); no slots, so no recipes
PIPELINE = "bind.v1"

if __name__ == "__main__":
    run.main(__file__, __doc__, options, models, pipeline)
