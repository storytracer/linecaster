---
schema: linecaster.preset/1
id: kraken-ppocrv6-small
edition: 1
step: recognition
model:
  id: kraken-ppocrv6-small
  revision: 49c249bf81d95ab2c5f699638d066f7935da6f16
engine: kraken.recognition.v1
options:
  model: small
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
  - 'storytracer/squiddleocr@7c8a052 (the settings its goldens were recorded with: sample-60, tables-7);
    -m small'
  created: 2026-11-03
support: experimental
---

kraken's PP-OCRv6 small recogniser through kraken's own code (`RecognitionTaskModel`), on every line of the
page in the line step's order.

- `batch_size` 8: the batch size squiddleocr's goldens were recorded with. kraken pads a batch to its widest
  line, so the batch size can move numerics; one page per request, batching only within the page.
- `precision` auto: bf16-mixed on CUDA (the model was trained in bf16-mixed; recognition about 1.6x faster on the
  GB10; 79 of 3,673 lines on 100 BHL pages read differently from 32-true), 32-true on the CPU. Needs the kraken fork with the
  inference autocast fix (storytracer/kraken 3d235ee8); on upstream kraken 7.1 the setting is inert.
  T4-class GPUs have no bf16 tensor cores: use 16-mixed or 32-true there (a new preset).
- `text_direction` horizontal-lr; right-to-left material wants horizontal-rl.
- Not validated against the goldens (which use medium); the card says tiny and small trade accuracy for speed and memory.
