# chain.v1

*Pipeline · [`chain.py`](../../../pipelines/chain.py)*

A chain of smaller models, picked step by step from the catalogue's presets (`linecaster models`): text
lines and a line recogniser, optionally a layout model first (without one the page is one region) and table
and formula models after; then Unicode NFC, typography and document assembly. Page rows in OUT/rows; with
--files per-page hOCR/ALTO/PAGE/txt/md/json, with --exports the per-page md/txt/json squiddleocr writes, with
--texts one text per item in each text version.

    uv run pipelines/chain.py IMAGES OUT --lines pp-ocrv6-medium-det --recognizer kraken-ppocrv6-medium
    uv run pipelines/chain.py IMAGES OUT --layout pp-doclayoutv3 --lines pp-ocrv6-medium-det \
        --recognizer tesseract-best-latin --tables slanet-plus --formulas pp-formulanet-plus-l
    ... --set recognition.batch_size=4          # an option over the preset's
    ... --backend served                        # a server in the task
    uv run pipelines/chain.py serve --layout pp-doclayoutv3 ...    # linecaster serve with the presets named
    uv run pipelines/chain.py ray start --head --num-gpus 8        # then --on ray --tasks 64
    ... --on hf-jobs --commit <sha> --tasks 64

`linecaster.run` has the options every pipeline shares; `--recipe` fills the slots.

## Slots

Each slot takes a preset of that step; a recipe fills them all.

| Slot | Option |
|---|---|
| layout | `--layout` |
| lines | `--lines` |
| recognition | `--recognizer` |
| tables | `--tables` |
| formulas | `--formulas` |

## Options

Besides the options every pipeline shares (`linecaster.run`).

| Option | Values | Default | Description |
|---|---|---|---|
| `--layout` |  |  | layout preset (none: the page is one region) |
| `--lines` |  |  | line detection preset (needed) |
| `--recognizer` |  |  | line recogniser preset (needed) |
| `--tables` |  |  | table preset (needs --layout) |
| `--formulas` |  |  | formula preset (needs --layout; without, formulas are read as text) |
| `--set` |  | `[]` | an engine option over the preset's, e.g. recognition.batch_size=4; repeatable |
| `--text` | lines \\| reflow | `'lines'` | document text |
| `--files` |  |  | per-page files <item>/<page>.<ext> here |
| `--formats` |  | `'hocr,alto,page,txt,md,json'` | formats for --files |
| `--exports` |  |  | <page>.paddle.md/.txt/.json as squiddleocr writes them |
| `--texts` |  |  | per-item texts: <version>/<item>.txt\|.md and JSONL |
| `--window` | int | `32` | pages in flight per served step |
| `--endpoint-for` |  | `[]` | a different server for one step |

## Recipes

- [`squiddle`](../recipes/squiddle.md)
