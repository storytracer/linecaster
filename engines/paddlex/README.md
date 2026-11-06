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

## Install

The package is not on PyPI: install it from the repository, with linecaster from the same commit (it depends on
`linecaster>=0.0.1,<0.2`, the releases whose engine API, `linecaster.engines.api`, and data model it uses):

```bash
uv add "linecaster @ git+https://github.com/storytracer/linecaster@<commit>" \
       "linecaster-paddlex @ git+https://github.com/storytracer/linecaster@<commit>#subdirectory=engines/paddlex"
```

PaddleX pins OpenCV's GUI build; `stubs/opencv-contrib-python` swaps in the headless build of the same version
(list it as a direct dependency with that path as its source, as the pipeline scripts do).

## Tests

The engine's conformance (`linecaster.testing.check_engine`) and its own unit tests are in `engines/paddlex/tests/`.
They run in an environment that has the package; `tests/test_engines_catalog.py` installs every engine package
with the pipelines' pins (its PEP 723 block and lock), and runs other tests when given them:

```bash
uv run tests/test_engines_catalog.py engines/paddlex/tests
```

Tests marked `network` and `gpu` skip where the network or a CUDA device is missing: the conformance needs the network (the pinned `PaddlePaddle/<name>_onnx` and `_safetensors` snapshots); the formula engine's is `slow`.
