# kraken-ppocrv6-tiny

*Preset · edition 1 · recognition · experimental*

kraken's PP-OCRv6 tiny recognizer through kraken's own code (`RecognitionTaskModel`), on every line of the
page in the line step's order.

- `batch_size` 8: the batch size squiddleocr's goldens were recorded with. kraken pads a batch to its widest
  line, so the batch size can move numerics; one page per request, batching only within the page.
- `precision` auto: bf16-mixed on CUDA (the model was trained in bf16-mixed; recognition about 1.6x faster on the
  GB10; 79 of 3,673 lines on 100 BHL pages read differently from 32-true), 32-true on the CPU. Needs the kraken fork with the
  inference autocast fix (storytracer/kraken 3d235ee8); on upstream kraken 7.1 the setting is inert.
  T4-class GPUs have no bf16 tensor cores: use 16-mixed or 32-true there (a new preset).
- `text_direction` horizontal-lr; right-to-left material wants horizontal-rl.
- Not validated against the goldens (which use medium); the card says tiny and small trade accuracy for speed and memory.

|  |  |
|---|---|
| Step | recognition (reads lines) |
| Engine | [`kraken.recognition.v1`](../../engines/kraken.recognition.v1.md) |
| Model | [PP-OCRv6 (tiny)](../../models/kraken-ppocrv6-tiny.md) |
| Revision | [`045d350d5a7664054370539b87bab0e790724ee2`](https://huggingface.co/small-models-for-glam/kraken-ppocrv6-tiny/tree/045d350d5a7664054370539b87bab0e790724ee2) |
| License | Apache-2.0 |
| Produces | text, words, word_confidences, line_confidences |

## Options

| Option | Value |
|---|---|
| model | `tiny` |
| batch_size | `8` |
| precision | `auto` |
| text_direction | `horizontal-lr` |

## Provenance

- storytracer/squiddleocr@7c8a052 (the settings its goldens were recorded with: sample-60, tables-7); -m tiny
