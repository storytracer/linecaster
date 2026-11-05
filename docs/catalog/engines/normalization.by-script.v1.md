# normalization.by-script.v1

*Engine · normalization · package `linecaster`*

Normalization by script: each run of a text (characters of one script, with the Common and Inherited ones
after them) normalized by the strategy for its script, the rest by the default strategy (`"*"`). A preset
names the strategies in `by_script`.

|  |  |
|---|---|
| Class | `linecaster.engines:ByScriptNormalizationEngine` |
| Source | [normalization.py](../../../src/linecaster/engines/normalization.py) |
| Reads | pages |
| Produces | normalized |
| Scripts | all |
| Runs | in the pipeline's process |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `strategies` | `dict[str, Strategy]` |  | ISO 15924 script code, or * for every other script -> the strategy (a preset's by_script, resolved) |
