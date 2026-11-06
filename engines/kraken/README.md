# linecaster-kraken

linecaster engines for [kraken](https://github.com/mittagessen/kraken)'s PP-OCRv6 line recognizer on torch. The package holds code only: the presets that configure these engines and the models they load (pinned, with their upstream cards) live in [linecaster's catalog](../../docs/catalog/README.md).

| Engine | Class | Step |
|---|---|---|
| [`kraken.recognition.v1`](../../docs/catalog/engines/kraken.recognition.v1.md) | `linecaster_kraken:KrakenRecognitionEngine` | recognition: the text of every line |

Each engine is registered under its id in the entry-point group `linecaster.engines` and runs in a pipeline's process (`InProcess`) or behind `linecaster serve` (`Served`). A pipeline script installs the package with its pinned dependencies (see `pipelines/transcribe_modular.py`); the engine pages list its options and presets.
