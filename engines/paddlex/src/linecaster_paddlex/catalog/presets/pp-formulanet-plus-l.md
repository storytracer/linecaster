---
schema: linecaster.preset/1
id: pp-formulanet-plus-l
edition: 1
step: formulas
model:
  id: pp-formulanet-plus-l-safetensors
  revision: 6cc004a8e91ea3f3819b05317f40b290cbe99c2b
engine:
  kind: paddlex.formulas/1
  options:
    model_name: PP-FormulaNet_plus-L
    batch_size: 8
capabilities:
  unit: region
  produces:
  - formulas
  - latex
provenance:
  derived_from:
  - 'storytracer/squiddleocr@7c8a052 (the settings its goldens were recorded with: sample-60, tables-7)'
  created: 2026-11-03
support: core
---

PP-FormulaNet_plus-L on every `formula` region (display formulas; inline formulas are not handled): the region's crop in,
LaTeX out, into `region.extra["formula"]`. The model runs on PaddleX's transformers engine (Hugging Face
transformers on torch, the same GPU as kraken); the official model source has no ONNX package for any formula
model and Paddle Inference is not used. The page's crops are read together, `batch_size` 8 per pass (squiddleocr's
`--batch-size` applies to the formula model too).
The squiddle combination's formula step: 29/29 formulas identical to squiddleocr on its formula test pages.
