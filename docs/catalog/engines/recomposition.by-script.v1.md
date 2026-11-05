# recomposition.by-script.v1

*Engine · recomposition · package `linecaster`*

Recomposition by script: each decision at a row end (a division mark, the separator between two rows) made
by the strategy for the script around it (the characters before the row end, else after it), the rest by the
default strategy (`"*"`), which also recomposes the item. A preset names the strategies in `by_script`.

|  |  |
|---|---|
| Class | `linecaster.engines:ByScriptRecompositionEngine` |
| Source | [recomposition.py](../../../src/linecaster/engines/recomposition.py) |
| Reads | items |
| Produces | paragraphs |
| Scripts | all |
| Runs | in the pipeline's process |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `strategies` | `dict[str, Strategy]` |  | ISO 15924 script code, or * for every other script -> the strategy (a preset's by_script, resolved) |
