# layout.single-region.v1

*Engine · layout · package `linecaster`*

No layout analysis: the whole page is one region (plain OCR; what squiddleocr's `--layout none` does). The
transcription's regions are replaced by one region covering the page image, reading order 0, score 1; a line
step on the whole page and the `LineAssigner` then put every line into it, and no table or formula regions
exist. A layout engine like the model ones (`__call__(image, transcription)`, the page image as an RGB array),
built in and in the pipeline's process only.

|  |  |
|---|---|
| Class | `linecaster.engines:SingleRegionLayoutEngine` |
| Source | [layout.py](../../../src/linecaster/engines/layout.py) |
| Reads | pages |
| Produces | regions, reading_order |
| Scripts | all |
| Runs | in the pipeline's process |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `label` | `str` | `'text'` | the region's label |
| `region_id` | `str` | `'page'` | the region's id |

## Presets

- [`single-region`](../presets/layout/single-region.md)
