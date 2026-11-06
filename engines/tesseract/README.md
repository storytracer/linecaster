# linecaster-tesseract

linecaster engines for [Tesseract](https://github.com/tesseract-ocr/tesseract)'s LSTM line recognizer through tesserocr. The package holds code only: the presets that configure these engines and the models they load (pinned, with their upstream cards) live in [linecaster's catalog](../../docs/catalog/README.md).

| Engine | Class | Step |
|---|---|---|
| [`tesseract.recognition.v1`](../../docs/catalog/engines/tesseract.recognition.v1.md) | `linecaster_tesseract:TesseractRecognitionEngine` | recognition: the text of every line |

Each engine is registered under its id in the entry-point group `linecaster.engines` and runs in a pipeline's process (`InProcess`) or behind `linecaster serve` (`Served`). A pipeline script installs the package with its pinned dependencies (see `pipelines/transcribe_modular.py`); the engine pages list its options and presets.
