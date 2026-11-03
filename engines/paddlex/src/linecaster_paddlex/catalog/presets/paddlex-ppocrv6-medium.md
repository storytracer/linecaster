---
schema: linecaster.preset/1
id: paddlex-ppocrv6-medium
edition: 1
step: recognition
model:
  id: pp-ocrv6-medium-rec-onnx
  revision: 50c7eacafc52fa7bcf4194e8cd08e46f8558504b
engine:
  kind: paddlex.recognition/1
  options:
    model_name: PP-OCRv6_medium_rec
    batch_size: 8
    words: true
capabilities:
  unit: line
  produces:
  - text
  - words
  - line_confidences
provenance:
  derived_from:
  - 'storytracer/linecaster@7beadcc (NOTES: More line recognisers, the comparison on sample-60)'
  created: 2026-11-03
support: experimental
---

PaddleOCR's own PP-OCRv6 medium recogniser on PaddleX's ONNX Runtime engine. Lines are cut as PaddleX's OCR
pipeline cuts them (minimum-area rectangle of the polygon, warped upright), sorted by aspect ratio and read
`batch_size` 8 at a time, as PaddleX's pipeline does. Words: the text split at whitespace, placed along the line by
the CTC columns of their characters (PaddleX's `return_word_box`); PaddleX gives no per-word confidence.

On the 60-page BHL sample (2026-11-03, `evidence/`) the same chain with kraken's port of the model family read
better on every volume but one; the likely difference is the line image (kraken's polygon-based extraction
against PaddleX's rectangle warp). Not investigated further.
