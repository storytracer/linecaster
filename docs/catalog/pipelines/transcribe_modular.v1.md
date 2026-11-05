# transcribe_modular.v1

*Pipeline · [`transcribe_modular.py`](../../../pipelines/transcribe_modular.py)*

The modular pipeline: smaller models, picked step by step from the catalog's presets (`linecaster models`):
text lines and a line recogniser, optionally a layout model first (without one the page is one region) and table
and formula models after; then Unicode NFC, typography and page composition. Page records in OUT/pages; with
--files per-page files in the --formats asked for (--naming squiddleocr: flat `<page>.paddle.<ext>`, as
squiddleocr names them), with --item-texts one text per item in each text version.

    uv run pipelines/transcribe_modular.py IMAGES OUT --lines pp-ocrv6-medium-det --recognition kraken-ppocrv6-medium
    uv run pipelines/transcribe_modular.py IMAGES OUT --layout pp-doclayoutv3 --lines pp-ocrv6-medium-det \
        --recognition tesseract-best-latin --tables slanet-plus --formulas pp-formulanet-plus-l
    ... --set recognition.batch_size=4          # an option over the preset's
    ... --backend served                        # a server in the task
    ... --files OUT/files --formats md,txt,json --naming squiddleocr --furniture    # squiddleocr's per-page files
    uv run pipelines/transcribe_modular.py serve --layout pp-doclayoutv3 ...    # linecaster serve with the presets named
    uv run pipelines/transcribe_modular.py ray start --head --num-gpus 8        # then --on ray --tasks 64
    ... --on hf-jobs --commit <sha> --tasks 64

`linecaster.runtime.run` has the options every pipeline shares; `--recipe` fills the slots.

## Slots

Each slot takes a preset of that step; a recipe fills them all.

| Slot | Option |
|---|---|
| layout | `--layout` |
| lines | `--lines` |
| recognition | `--recognition` |
| tables | `--tables` |
| formulas | `--formulas` |

## Options

Besides the options every pipeline shares (`linecaster.runtime.run`).

| Option | Values | Default | Description |
|---|---|---|---|
| `--layout` |  |  | layout preset (none: the page is one region) |
| `--lines` |  |  | line detection preset (needed) |
| `--recognition` |  |  | line recognition preset (needed) |
| `--tables` |  |  | table preset (needs --layout) |
| `--formulas` |  |  | formula preset (needs --layout; without, formulas are read as text) |
| `--set` |  | `[]` | an engine option over the preset's, e.g. recognition.batch_size=4; repeatable |
| `--text` | lines \\| reflow | `'lines'` | document text |
| `--files` |  |  | per-page files here, one per format (--formats, --naming) |
| `--formats` |  | `'hocr,alto,page,txt,md,json'` |  |
| `--naming` |  | `'item'` | --files names: item, <item>/<page>.<ext>; squiddleocr, <page>.paddle.<ext> in one folder |
| `--furniture` | flag |  | --files: keep page headers and footers in md, txt and html (as squiddleocr does) |
| `--item-texts` |  |  | per-item texts: <version>/<item>.txt\|.md and JSONL |
| `--window` | int | `32` | pages in flight per served step |
| `--endpoint-for` |  | `[]` | a different server for one step |

## Recipes

- [`squiddle`](../recipes/squiddle.md)
