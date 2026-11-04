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
r"""The item stage: one text per item (book, issue, manuscript) and text version, from the page rows of a first
stage written in item shards (`--item-shards N`). Each task reads whole shard folders, so it sees every page of
its items; no engine or GPU is needed.

    uv run pipelines/chain.py IMAGES OUT1 ... --tasks 4000 --item-shards 64
    uv run pipelines/items.py OUT1/rows OUT2 --tasks 64
    ... --on hf-jobs --commit <sha> --flavor cpu-upgrade --tasks 64

Texts in OUT2/texts/<version>/<rank>.jsonl.gz; with --files also OUT2/files/<version>/<item>.txt|.md.
``linecaster.run`` has the options every pipeline shares (IMAGES is the first stage's rows folder here).
"""
from linecaster import run
from linecaster.blocks.readers import PageRowReader
from linecaster.blocks.texts import ItemTexts
from linecaster.blocks.writers import ItemTextFilesWriter, ItemTextJsonlWriter


def options(ap):
    ap.add_argument("--files", action="store_true", help="also one file per item and version: OUT/files/...")


def models(a) -> list[dict]:
    return []


def pipeline(a, script: str) -> list:
    out = a.out.rstrip("/")
    return [
        PageRowReader(a.images, fetch_images=False, item_shards=True),
        ItemTexts(),
        *([ItemTextFilesWriter(f"{out}/files")] if a.files else []),
        ItemTextJsonlWriter(f"{out}/texts", output_filename="${variant}/${rank}.jsonl.gz"),
    ], {"engines": False}


if __name__ == "__main__":
    run.main(__file__, __doc__, options, models, pipeline)
