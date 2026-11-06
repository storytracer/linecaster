# linecaster-paddlex

linecaster engines for [PaddleX](https://github.com/PaddlePaddle/PaddleX)'s layout analysis, text-line detection, text recognition, table and formula recognition, on ONNX Runtime (formulas on torch). The package holds code only: the presets that configure these engines and the models they load (pinned, with their upstream cards) live in [linecaster's catalog](../../docs/catalog/README.md).

| Engine | Class | Step |
|---|---|---|
| [`paddlex.layout.v1`](../../docs/catalog/engines/paddlex.layout.v1.md) | `linecaster_paddlex:PaddleLayoutEngine` | layout: regions with labels and reading order |
| [`paddlex.lines.v1`](../../docs/catalog/engines/paddlex.lines.v1.md) | `linecaster_paddlex:PaddleLineEngine` | lines: text lines with their geometry |
| [`paddlex.recognition.v1`](../../docs/catalog/engines/paddlex.recognition.v1.md) | `linecaster_paddlex:PaddleRecognitionEngine` | recognition: the text of every line |
| [`paddlex.tables.v1`](../../docs/catalog/engines/paddlex.tables.v1.md) | `linecaster_paddlex:PaddleTableEngine` | tables: the structure of table regions |
| [`paddlex.formulas.v1`](../../docs/catalog/engines/paddlex.formulas.v1.md) | `linecaster_paddlex:PaddleFormulaEngine` | formulas: formula regions as LaTeX |

Each engine is registered under its id in the entry-point group `linecaster.engines` and runs in a pipeline's process (`InProcess`) or behind `linecaster serve` (`Served`). A pipeline script installs the package with its pinned dependencies (see `pipelines/transcribe_modular.py`); the engine pages list its options and presets.
