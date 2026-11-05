# paddlex.formulas.v1

*Engine · formulas · package `linecaster-paddlex`*

linecaster engine model for the formulas step: LaTeX for every `formula` region, into
`region.extra["formula"]`. The page's formula crops are read together, in the regions' list order,
`batch_size` crops per forward pass (a page's result depends only on the page). The model files:
`weights` (a catalogue pin of the `_safetensors` package) or the catalogue's newest pin for
`model_name` (`weights.resolve`).

|  |  |
|---|---|
| Class | `linecaster_paddlex:PaddleFormulaEngine` |
| Source | [formulas.py](../../../engines/paddlex/src/linecaster_paddlex/formulas.py) |
| Reads | regions |
| Produces | formulas, latex |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `model_name` | `str` | `DEFAULT_FORMULA_MODEL` | PaddleX formula recogniser on the transformers engine: PP-FormulaNet_plus-L or PP-FormulaNet-L |
| `device` | `str` | `'auto'` | auto (CUDA if available) or cpu (torch) |
| `batch_size` | `int` | `8` | formula crops per forward pass |

## Presets

- [`pp-formulanet-l`](../presets/formulas/pp-formulanet-l.md)
- [`pp-formulanet-plus-l`](../presets/formulas/pp-formulanet-plus-l.md)
