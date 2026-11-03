---
schema: linecaster.preset/1
id: kraken-ppocrv6-medium
edition: 1
step: recognition
model:
  id: kraken-ppocrv6-medium
  revision: f7fd70f3fd22b615f41bada4674ac2462f938339
engine: kraken.recognition.v1
options:
  model: medium
  batch_size: 8
  precision: auto
  text_direction: horizontal-lr
capabilities:
  unit: line
  produces:
  - text
  - words
  - word_confidences
  - line_confidences
provenance:
  derived_from:
  - 'storytracer/squiddleocr@7c8a052 (the settings its goldens were recorded with: sample-60, tables-7)'
  created: 2026-11-03
support: core
---

kraken's PP-OCRv6 medium recogniser through kraken's own code (`RecognitionTaskModel`), on every line of the
page in the line step's order; the squiddle combination's recogniser, which reproduces squiddleocr's goldens line for line (1,560/1,560 lines on sample-60, spark and forge).

- `batch_size` 8: the batch size squiddleocr's goldens were recorded with. kraken pads a batch to its widest
  line, so the batch size can move numerics; one page per request, batching only within the page.
- `precision` auto: bf16-mixed on CUDA (the model was trained in bf16-mixed; recognition about 1.6x faster on the
  GB10; 79 of 3,673 lines on 100 BHL pages read differently from 32-true), 32-true on the CPU. Needs the kraken fork with the
  inference autocast fix (storytracer/kraken 3d235ee8); on upstream kraken 7.1 the setting is inert.
  T4-class GPUs have no bf16 tensor cores: use 16-mixed or 32-true there (a new preset).
- `text_direction` horizontal-lr; right-to-left material wants horizontal-rl.

