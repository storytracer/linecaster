# tesseract-fast-latin

*Preset · edition 1 · recognition · experimental*

Tesseract 5 (LSTM, tesserocr 2.12.0 with Tesseract 5.5.3) with `script/Latin` (the Latin script model) from tessdata_fast, on
every line the line step found: page segmentation mode 7 (one line of text) on the line's bounding box, outside the
polygon painted white, 4 px white padding, 300 dpi assumed. Words, boxes and confidences are Tesseract's. CPU
only, one line at a time.
tessdata_fast was not part of the 2026-11-03 comparison; integer models, faster and less accurate than tessdata_best.

|  |  |
|---|---|
| Step | recognition (reads lines) |
| Engine | [`tesseract.recognition.v1`](../../engines/tesseract.recognition.v1.md) |
| Model | [tessdata_fast](../../models/tessdata-fast.md) |
| Revision | [`87416418657359cb625c412a48b6e1d6d41c29bd`](https://github.com/tesseract-ocr/tessdata_fast/tree/87416418657359cb625c412a48b6e1d6d41c29bd) |
| Licence | Apache-2.0 |
| Produces | text, words, word_confidences, line_confidences |

## Options

| Option | Value |
|---|---|
| lang | `script/Latin` |
| data | `fast` |
| pad | `4` |
| dpi | `300` |

## Provenance

- storytracer/linecaster@7beadcc (NOTES: More line recognisers, the comparison on sample-60)
