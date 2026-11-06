# composition.docling.v1

*Engine · composition · package `linecaster`*

A DoclingDocument from a page's regions, paragraphs or lines, and tables
(`linecaster.formats.docling.DocumentBuilder`): titles and section headers at their heading levels, text
items with Docling's labels, page headers and footers in the furniture layer, tables with their cells,
formulas, pictures with the text read inside them, optionally one section group per heading; the map of items
to regions in `extra["docling_region_of"]`. A text region is composed from its paragraphs when a
recomposition made them (one item per paragraph, continued paragraphs in one item), else from its lines as laid
out (one item per region, one row per line: diplomatic composition).

The page unit is the call; an item's document (all its pages, in order, paragraphs continued across pages) is
`item_document`.

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
| `sections` | `bool` | `False` | every heading opens a section group up to the next heading |

## Presets

- [`docling-composition`](../presets/composition/docling-composition.md)
