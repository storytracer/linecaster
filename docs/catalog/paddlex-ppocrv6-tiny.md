# paddlex-ppocrv6-tiny

*Edition 1 · recognition · experimental*

PaddleOCR's own PP-OCRv6 tiny recogniser on PaddleX's ONNX Runtime engine. Lines are cut as PaddleX's OCR
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
| Model | [PP-OCRv6_tiny_rec](https://huggingface.co/PaddlePaddle/PP-OCRv6_tiny_rec_onnx/tree/2612ab37152ae0a677521bae4e1e3d4fb4cf7c30) |
| Revision | `2612ab37152ae0a677521bae4e1e3d4fb4cf7c30` |
| Upstream card | [upstream/2612ab37152ae0a677521bae4e1e3d4fb4cf7c30/README.md](../../engines/paddlex/src/linecaster_paddlex/catalog/models/pp-ocrv6-tiny-rec-onnx/upstream/2612ab37152ae0a677521bae4e1e3d4fb4cf7c30/README.md) (verbatim, at that revision) |
| Licence | Apache-2.0 |
| Languages | eng, zho |
| Derived from | converted of PaddlePaddle/PP-OCRv6_tiny_rec |
| Produces | text, words, line_confidences |

## Evidence

| Date | Source | Dataset | Result |
|---|---|---|---|
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_diplomatic 0.0446, cer_reading 0.0376, recall 0.9123, wall_seconds 33 |

## Provenance

- storytracer/linecaster@7beadcc (NOTES: More line recognisers, the comparison on sample-60)
