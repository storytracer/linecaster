# bind.v1

*Pipeline · [`bind.py`](../../../pipelines/bind.py)*

The item stage (binding): one text per item (book, issue, manuscript) and text version, from the page records of a first
stage written in item shards (`--item-shards N`). Each task reads whole shard folders, so it sees every page of
its items; no engine or GPU is needed.

    uv run pipelines/transcribe_modular.py IMAGES OUT1 ... --tasks 4000 --item-shards 64
    uv run pipelines/bind.py OUT1/pages OUT2 --tasks 64
    ... --on hf-jobs --commit <sha> --flavor cpu-upgrade --tasks 64

Texts in OUT2/texts/<version>/<rank>.jsonl.gz; with --files also OUT2/files/<version>/<item>.txt|.md.
`linecaster.runtime.run` has the options every pipeline shares (IMAGES is the first stage's page records folder here).

## Options

Besides the options every pipeline shares (`linecaster.runtime.run`).

| Option | Values | Default | Description |
|---|---|---|---|
| `--files` | flag |  | also one file per item and version: OUT/files/... |
