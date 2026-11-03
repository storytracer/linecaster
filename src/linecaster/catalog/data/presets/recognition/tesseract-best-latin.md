---
schema: linecaster.preset/1
id: tesseract-best-latin
edition: 1
step: recognition
model:
  id: tessdata-best
  revision: e12c65a915945e4c28e237a9b52bc4a8f39a0cec
engine: tesseract.recognition.v1
options:
  lang: script/Latin
  data: best
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

Tesseract 5 (LSTM, tesserocr 2.12.0 with Tesseract 5.5.3) with `script/Latin` (the Latin script model) from tessdata_best, on
every line the line step found: page segmentation mode 7 (one line of text) on the line's bounding box, outside the
polygon painted white, 4 px white padding, 300 dpi assumed. Words, boxes and confidences are Tesseract's. CPU
only, one line at a time.
On the 60-page BHL sample (2026-11-03, `evidence/`) `script/Latin` came close to PP-OCRv6 tiny; `eng` alone lost on the German, French, Latin and Russian volumes.
