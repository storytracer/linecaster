# tesseract.recognition.v1

*Engine · recognition · package `linecaster-tesseract`*

linecaster engine model for the recognition step: Tesseract 5 (LSTM) on every line of the
transcription. `lang` is a tessdata language or script (`eng`, `deu+lat`, `script/Latin`),
`data` `best` or `fast`. Fills text, confidence and words with boxes and confidences.
The language data: `weights` (a catalogue pin; only its files) or `data`'s newest pin in the catalogue.

|  |  |
|---|---|
| Class | `linecaster_tesseract:TesseractRecognitionEngine` |
| Source | [recognizer.py](../../../engines/tesseract/src/linecaster_tesseract/recognizer.py) |
| Reads | lines |
| Produces | text, words, word_confidences, line_confidences |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `lang` | `str` | `'eng'` | tessdata language or script, + for several: eng, deu+lat, script/Latin |
| `data` | `Literal['best', 'fast']` | `'best'` | tessdata_best (float LSTM, most accurate) or tessdata_fast (integer, faster); with weights, the data set the pin belongs to |
| `pad` | `int` | `4` | white pixels around each line image |
| `dpi` | `int` | `300` | the resolution Tesseract assumes (user_defined_dpi) |

## Presets

- [`tesseract-best-eng`](../presets/recognition/tesseract-best-eng.md)
- [`tesseract-best-latin`](../presets/recognition/tesseract-best-latin.md)
- [`tesseract-fast-eng`](../presets/recognition/tesseract-fast-eng.md)
- [`tesseract-fast-latin`](../presets/recognition/tesseract-fast-latin.md)
