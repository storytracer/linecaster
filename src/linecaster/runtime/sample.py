"""A run's sample on disk: ``OUT/sample.parquet``, one row per sample page in the sample's order, with the rule in
the file's metadata (``linecaster.data.sample``; ``--sample``, ``linecaster sample``)."""
from __future__ import annotations

import json

from ..data.sample import RULE, Sample

#: the sample's file in the run folder
SAMPLE_FILE = "sample.parquet"


def sample_schema():
    """The columns of ``sample.parquet``."""
    import pyarrow as pa

    return pa.schema([("rank", pa.int64()), ("item_id", pa.string()), ("page_id", pa.string()),
                      ("item_rank", pa.int64()), ("page_rank", pa.int64()), ("item_hash", pa.uint64()),
                      ("page_hash", pa.uint64()), ("item_pages", pa.int64())])


def sample_table(sample: Sample):
    """The sample as a ``pyarrow.Table`` (``sample_schema``), its run-record section as the file's metadata
    (``linecaster.sample``)."""
    import pyarrow as pa

    schema = sample_schema()
    columns = {name: [getattr(s, name) for s in sample.selected] for name in schema.names}
    meta = {b"linecaster.sample": json.dumps(sample.record(), sort_keys=True).encode(), b"rule": RULE.encode()}
    return pa.table(columns, schema=schema.with_metadata(meta))


def write_sample(out: str, sample: Sample, name: str = SAMPLE_FILE) -> str:
    """Write the sample as ``OUT/<name>`` (any fsspec folder, through datatrove's ``DataFolder``). The same sample
    gives the same bytes. Returns the file's path."""
    import pyarrow.parquet as pq
    from datatrove.io import get_datafolder

    folder = get_datafolder(out)
    with folder.open(name, "wb") as f:
        pq.write_table(sample_table(sample), f, compression="zstd")
    return folder.resolve_paths(name)


def sample_reader(pipeline: list):
    """The pipeline's reader that reads a sample (one with a ``sample`` rule), or None."""
    return next((b for b in pipeline if getattr(b, "sample", None) is not None and hasattr(b, "sampled")), None)
