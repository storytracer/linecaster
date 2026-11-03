# tesseract-best-eng

*Preset · edition 1 · recognition · experimental*

Tesseract 5 (LSTM, tesserocr 2.12.0 with Tesseract 5.5.3) with `eng` (English) from tessdata_best, on
every line the line step found: page segmentation mode 7 (one line of text) on the line's bounding box, outside the
polygon painted white, 4 px white padding, 300 dpi assumed. Words, boxes and confidences are Tesseract's. CPU
only, one line at a time.
On the 60-page BHL sample (2026-11-03, `evidence/`) `script/Latin` came close to PP-OCRv6 tiny; `eng` alone lost on the German, French, Latin and Russian volumes.

|  |  |
|---|---|
| Step | recognition (reads lines) |
| Engine | [`tesseract.recognition.v1`](../../engines/tesseract.recognition.v1.md) |
| Model | [tessdata_best](../../models/tessdata-best.md) |
| Revision | [`e12c65a915945e4c28e237a9b52bc4a8f39a0cec`](https://github.com/tesseract-ocr/tessdata_best/tree/e12c65a915945e4c28e237a9b52bc4a8f39a0cec) |
| Licence | Apache-2.0 |
| Produces | text, words, word_confidences, line_confidences |

## Options

| Option | Value |
|---|---|
| lang | `eng` |
| data | `best` |
| pad | `4` |
| dpi | `300` |

## Evidence

| Date | Source | Dataset | Result |
|---|---|---|---|
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 (chain.v1 with pp-doclayoutv3@1, pp-ocrv6-medium-det@1, slanet-plus@1, no formulas, text lines; only the recogniser varied) | cer_diplomatic 0.0595, cer_reading 0.0516, recall 0.857, wall_seconds 110 |

## Provenance

- storytracer/linecaster@7beadcc (NOTES: More line recognisers, the comparison on sample-60)
