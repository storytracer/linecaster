# kraken.recognition.v1

*Engine · recognition · package `linecaster-kraken`*

linecaster engine for the recognition step: kraken's PP-OCRv6 recognizer on every line of
the transcription, in list order (the line step's processing order), `batch_size` lines per
forward pass. A page's result depends only on the page. Fills text, confidence and words.

The model file: `weights` (a catalog pin, as a preset passes it) when given, else `model`: a size
name, resolved to its model document's newest pin, or a kraken model file.

|  |  |
|---|---|
| Class | `linecaster_kraken:KrakenRecognitionEngine` |
| Source | [recognizer.py](../../../engines/kraken/src/linecaster_kraken/recognizer.py) |
| Reads | lines |
| Produces | text, words, word_confidences, line_confidences |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `model` | `str` | `'medium'` | PP-OCRv6 size (tiny, small, medium) or a path to a kraken model file; with weights, the size the pin is of |
| `device` | `str` | `'auto'` | auto (CUDA if available), cpu or cuda |
| `batch_size` | `int` | `8` | lines per forward pass; kraken pads a batch to its widest line, so the batch size can move numerics |
| `precision` | `str` | `'auto'` | Lightning precision at inference; auto: bf16-mixed on CUDA (the training precision), 32-true on the CPU |
| `text_direction` | `Literal['horizontal-lr', 'horizontal-rl', 'vertical-lr', 'vertical-rl']` | `'horizontal-lr'` | kraken's text direction of the lines (horizontal-rl: right to left) |
| `compile_backbone` | `bool` | `False` | torch.compile the backbone (dynamic shapes): fewer kernel launches, minutes of compiling when the model loads; moves a few characters |

## Presets

- [`kraken-ppocrv6-medium`](../presets/recognition/kraken-ppocrv6-medium.md)
- [`kraken-ppocrv6-small`](../presets/recognition/kraken-ppocrv6-small.md)
- [`kraken-ppocrv6-tiny`](../presets/recognition/kraken-ppocrv6-tiny.md)
