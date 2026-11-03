# paddlex-ppocrv6-small

*Edition 1 · recognition · experimental*

PaddleOCR's own PP-OCRv6 small recogniser on PaddleX's ONNX Runtime engine. Lines are cut as PaddleX's OCR
pipeline cuts them (minimum-area rectangle of the polygon, warped upright), sorted by aspect ratio and read
`batch_size` 8 at a time, as PaddleX's pipeline does. Words: the text split at whitespace, placed along the line by
the CTC columns of their characters (PaddleX's `return_word_box`); PaddleX gives no per-word confidence.

On the 60-page BHL sample (2026-11-03, `evidence/`) the same chain with kraken's port of the model family read
better on every volume but one; the likely difference is the line image (kraken's polygon-based extraction
against PaddleX's rectangle warp). Not investigated further.

| | |
|---|---|
| Step | recognition (reads lines) |
| Engine | `paddlex.recognition/1` |
| Model | [PP-OCRv6_small_rec](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_rec_onnx/tree/b8f84f0b80c529de40b4fbb3544b84fa7233a513) |
| Revision | `b8f84f0b80c529de40b4fbb3544b84fa7233a513` |
| Upstream card | [upstream/b8f84f0b80c529de40b4fbb3544b84fa7233a513/README.md](../../engines/paddlex/src/linecaster_paddlex/catalog/models/pp-ocrv6-small-rec-onnx/upstream/b8f84f0b80c529de40b4fbb3544b84fa7233a513/README.md) (verbatim, at that revision) |
| Licence | Apache-2.0 |
| Languages | eng, zho |
| Derived from | converted of PaddlePaddle/PP-OCRv6_small_rec |
| Produces | text, words, line_confidences |

## Evidence

| Date | Source | Dataset | Result |
|---|---|---|---|
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 (chain/1 with pp-doclayoutv3@1, pp-ocrv6-medium-det@1, slanet-plus@1, no formulas, text lines; only the recogniser varied) | cer_diplomatic 0.0375, cer_reading 0.03, recall 0.9351, wall_seconds 44 |

## Provenance

- storytracer/linecaster@7beadcc (NOTES: More line recognisers, the comparison on sample-60)
