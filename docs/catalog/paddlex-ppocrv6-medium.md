# paddlex-ppocrv6-medium

*Edition 1 · recognition · experimental*

PaddleOCR's own PP-OCRv6 medium recogniser on PaddleX's ONNX Runtime engine. Lines are cut as PaddleX's OCR
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
| Model | [PP-OCRv6_medium_rec](https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_rec_onnx/tree/50c7eacafc52fa7bcf4194e8cd08e46f8558504b) |
| Revision | `50c7eacafc52fa7bcf4194e8cd08e46f8558504b` |
| Upstream card | [upstream/50c7eacafc52fa7bcf4194e8cd08e46f8558504b/README.md](../../engines/paddlex/src/linecaster_paddlex/catalog/models/pp-ocrv6-medium-rec-onnx/upstream/50c7eacafc52fa7bcf4194e8cd08e46f8558504b/README.md) (verbatim, at that revision) |
| Licence | Apache-2.0 |
| Languages | eng, zho |
| Derived from | converted of PaddlePaddle/PP-OCRv6_medium_rec |
| Produces | text, words, line_confidences |

## Evidence

| Date | Source | Dataset | Result |
|---|---|---|---|
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_diplomatic 0.0387, cer_reading 0.0315, recall 0.9343, wall_seconds 49 |

## Provenance

- storytracer/linecaster@7beadcc (NOTES: More line recognisers, the comparison on sample-60)
