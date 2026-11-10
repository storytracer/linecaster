# linecaster-tesseract

linecaster engines for [Tesseract](https://github.com/tesseract-ocr/tesseract)'s LSTM line recognizer through tesserocr. The package holds code only: the presets that configure these engines and the models they load (pinned, with their upstream cards) live in [linecaster's catalog](https://storytracer.github.io/linecaster/latest/catalog/).

| Engine | Class | Step |
|---|---|---|
| [`tesseract.recognition.v1`](https://storytracer.github.io/linecaster/latest/catalog/engines/tesseract.recognition.v1/) | `linecaster_tesseract:TesseractRecognitionEngine` | recognition: the text of every line |

Each engine is registered under its id in the entry-point group `linecaster.engines` and runs in a pipeline's process (`InProcess`) or behind `linecaster serve` (`Served`). A pipeline script installs the package with its pinned dependencies (see `pipelines/transcribe_modular.py`); the engine pages list its options and presets.

## Install

The package is not on PyPI: install it from the repository, with linecaster from the same commit (it depends on
`linecaster>=0.1,<0.6`, the releases whose engine API, `linecaster.engines.api`, and data model it uses):

```bash
uv add "linecaster @ git+https://github.com/storytracer/linecaster@<commit>" \
       "linecaster-tesseract @ git+https://github.com/storytracer/linecaster@<commit>#subdirectory=engines/tesseract"
```

The tesserocr wheels bundle Tesseract and Leptonica on Linux (aarch64 and x86_64): no system packages.

## Tests

The engine's conformance (`linecaster.testing.check_engine`) and its own unit tests are in `engines/tesseract/tests/`.
They run in an environment that has the package; `tests/test_engines_catalog.py` installs every engine package
with the pipelines' pins (its PEP 723 block and lock), and runs other tests when given them:

```bash
uv run tests/test_engines_catalog.py engines/tesseract/tests
```

Tests marked `network` and `gpu` skip where the network or a CUDA device is missing: the conformance needs the network (the pinned tessdata files from GitHub).
