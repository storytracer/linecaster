# linecaster-kraken

linecaster engines for [kraken](https://github.com/mittagessen/kraken)'s PP-OCRv6 line recognizer on torch. The package holds code only: the presets that configure these engines and the models they load (pinned, with their upstream cards) live in [linecaster's catalog](../../docs/catalog/README.md).

| Engine | Class | Step |
|---|---|---|
| [`kraken.recognition.v1`](../../docs/catalog/engines/kraken.recognition.v1.md) | `linecaster_kraken:KrakenRecognitionEngine` | recognition: the text of every line |

Each engine is registered under its id in the entry-point group `linecaster.engines` and runs in a pipeline's process (`InProcess`) or behind `linecaster serve` (`Served`). A pipeline script installs the package with its pinned dependencies (see `pipelines/transcribe_modular.py`); the engine pages list its options and presets.

## Install

The package is not on PyPI: install it from the repository, with linecaster from the same commit (it depends on
`linecaster>=0.0.1,<0.2`, the releases whose engine API, `linecaster.engines.api`, and data model it uses):

```bash
uv add "linecaster @ git+https://github.com/storytracer/linecaster@<commit>" \
       "linecaster-kraken @ git+https://github.com/storytracer/linecaster@<commit>#subdirectory=engines/kraken"
```

kraken itself comes from our fork (the PP-OCRv6 code with the inference precision fix): a project that installs
this package lists `kraken` as a direct dependency with the fork as its source, as `pipelines/transcribe_modular.py`
does, because uv applies sources only to a project's own dependencies.

## Tests

The engine's conformance (`linecaster.testing.check_engine`) and its own unit tests are in `engines/kraken/tests/`.
They run in an environment that has the package; `tests/test_engines_catalog.py` installs every engine package
with the pipelines' pins (its PEP 723 block and lock), and runs other tests when given them:

```bash
uv run tests/test_engines_catalog.py engines/kraken/tests
```

Tests marked `network` and `gpu` skip where the network or a CUDA device is missing: the CPU conformance needs the network (the weights come from the pinned Hugging Face mirror, `small-models-for-glam/kraken-ppocrv6-*`), the CUDA one a GPU too.
