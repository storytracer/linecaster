# tesseract-fast-latin

*Edition 1 · recognition · experimental*

Tesseract 5 (LSTM, tesserocr 2.12.0 with Tesseract 5.5.3) with `script/Latin` (the Latin script model) from tessdata_fast, on
every line the line step found: page segmentation mode 7 (one line of text) on the line's bounding box, outside the
polygon painted white, 4 px white padding, 300 dpi assumed. Words, boxes and confidences are Tesseract's. CPU
only, one line at a time.
tessdata_fast was not part of the 2026-11-03 comparison; integer models, faster and less accurate than tessdata_best.

| | |
|---|---|
| Step | recognition (reads lines) |
| Engine | `tesseract.recognition/1` |
| Model | [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast/tree/87416418657359cb625c412a48b6e1d6d41c29bd) |
| Revision | `87416418657359cb625c412a48b6e1d6d41c29bd` |
| Upstream card | [upstream/87416418657359cb625c412a48b6e1d6d41c29bd/README.md](../../engines/tesseract/src/linecaster_tesseract/catalog/models/tessdata-fast/upstream/87416418657359cb625c412a48b6e1d6d41c29bd/README.md) (verbatim, at that revision) |
| Licence | Apache-2.0 |
| Languages | eng, mul |
| Scripts | Latn |
| Produces | text, words, word_confidences, line_confidences |

## Provenance

- storytracer/linecaster@7beadcc (NOTES: More line recognisers, the comparison on sample-60)
