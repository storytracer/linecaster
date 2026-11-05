"""Item shards: a stable group for every item (book, issue, manuscript), so a later stage can read whole items.

A first stage distributes pages over tasks as datatrove distributes files, so one item's pages can land in
different tasks. Its page writer puts every page into its item's shard (``OUT/rows/<shard>/<rank>.jsonl.gz``,
``PageJsonlWriter(item_shards=N)``); every item lands in exactly one shard, whichever task read its pages. An
item-level stage then reads whole shard folders (``PageRowReader(item_shards=True)``), as datatrove's own
multi-stage pipelines read per-bucket folders. The shard is a hash of the item id, the same in every process.
"""
from __future__ import annotations

import hashlib

SHARD_KEY = "item_shard"


def item_shard(item_id: str, shards: int) -> str:
    """The shard folder name of an item: ``blake2b(item_id) mod shards``, zero-padded to five digits."""
    digest = hashlib.blake2b(item_id.encode("utf-8"), digest_size=8).digest()
    return f"{int.from_bytes(digest, 'big') % shards:05d}"
