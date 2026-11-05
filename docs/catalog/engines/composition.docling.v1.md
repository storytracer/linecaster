# composition.docling.v1

*Engine · composition · package `linecaster`*

A DoclingDocument from a page's regions, lines and tables (`linecaster.formats.docling.DocumentBuilder`):
titles and section headers at their heading levels, text items with Docling's labels, page headers and
footers in the furniture layer, tables with their cells, formulas, pictures with the text read inside them,
optionally one section group per heading; the map of items to regions in `extra["docling_region_of"]`.
`text`: one visual row per line (`lines`), or the rows recomposed into paragraphs (`reflow`).

|  |  |
|---|---|
| Class | `linecaster.engines:DoclingCompositionEngine` |
| Source | [composition.py](../../../src/linecaster/engines/composition.py) |
| Reads | pages |
| Produces | document |
| Scripts | all |
| Runs | in the pipeline's process |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `text` | `Literal['lines', 'reflow']` | `'lines'` | a text item's text: its rows as laid out (lines), or recomposed into paragraphs (reflow) |
| `sections` | `bool` | `False` | every heading opens a section group up to the next heading |
| `rtl` | `bool` | `False` | the writing direction is right to left (reflow's margins) |
