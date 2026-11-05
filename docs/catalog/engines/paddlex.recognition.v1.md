# paddlex.recognition.v1

*Engine · recognition · package `linecaster-paddlex`*

linecaster engine for the recognition step: a PaddleOCR text recognizer on every line of the
transcription (`RECOGNIZERS`). Fills text, confidence (the recognizer's mean character probability) and words
(positions only; PaddleX gives no per-word confidence). A page's result depends only on the page. The model
files: `weights` (a catalog pin) or the catalog's newest pin for `model_name` (`weights.resolve`).

|  |  |
|---|---|
| Class | `linecaster_paddlex:PaddleRecognitionEngine` |
| Source | [recognizer.py](../../../engines/paddlex/src/linecaster_paddlex/recognizer.py) |
| Reads | lines |
| Produces | text, words, line_confidences |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `model_name` | `str` | `'PP-OCRv6_medium_rec'` | PaddleX text recognizer: PP-OCRv6_{tiny,small,medium}_rec |
| `device` | `str` | `'auto'` | auto, cpu, cuda, tensorrt or coreml (ONNX Runtime providers) |
| `batch_size` | `int` | `8` | line images per forward pass (sorted by aspect ratio first, as PaddleX's pipeline does) |
| `words` | `bool` | `True` | word boxes from the CTC columns (PaddleX's return_word_box) |

## Presets

- [`paddlex-ppocrv6-medium`](../presets/recognition/paddlex-ppocrv6-medium.md)
- [`paddlex-ppocrv6-small`](../presets/recognition/paddlex-ppocrv6-small.md)
- [`paddlex-ppocrv6-tiny`](../presets/recognition/paddlex-ppocrv6-tiny.md)
