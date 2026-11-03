---
schema: linecaster.preset/1
id: tesseract-fast-eng
edition: 1
step: recognition
model:
  id: tessdata-fast
  revision: 87416418657359cb625c412a48b6e1d6d41c29bd
engine:
  kind: tesseract.recognition/1
  options:
    lang: eng
    data: fast
    pad: 4
    dpi: 300
capabilities:
  unit: line
  produces:
  - text
  - words
  - word_confidences
  - line_confidences
provenance:
  derived_from:
  - 'storytracer/linecaster@7beadcc (NOTES: More line recognisers, the comparison on sample-60)'
  created: 2026-11-03
support: experimental
---

Tesseract 5 (LSTM, tesserocr 2.12.0 with Tesseract 5.5.3) with tessdata_fast's English (`eng`), on every
line the line step found: page segmentation mode 7 (one line of text) on the line's bounding box, outside the
polygon painted white, 4 px white padding, 300 dpi assumed. Words, boxes and confidences are Tesseract's. CPU
only, one line at a time.
tessdata_fast was not part of the 2026-11-03 comparison; integer models, faster and less accurate than tessdata_best.
