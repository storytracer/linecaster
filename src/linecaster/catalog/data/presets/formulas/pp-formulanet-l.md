---
schema: linecaster.preset/1
id: pp-formulanet-l
edition: 1
step: formulas
model:
  id: pp-formulanet-l-safetensors
  revision: 69869f2891cc61347d230ef234bcc8b8d297c43a
engine: paddlex.formulas.v1
options:
  model_name: PP-FormulaNet-L
  batch_size: 8
capabilities:
  unit: region
  produces:
  - formulas
  - latex
provenance:
  derived_from:
  - 'storytracer/squiddleocr@7c8a052 (the settings its goldens were recorded with: sample-60, tables-7);
    --formula-model PP-FormulaNet-L'
  created: 2026-11-03
support: experimental
---

PP-FormulaNet-L on every `formula` region (display formulas; inline formulas are not handled): the region's crop in,
LaTeX out, into `region.extra["formula"]`. The model runs on PaddleX's transformers engine (Hugging Face
transformers on torch, the same GPU as kraken); the official model source has no ONNX package for any formula
model and Paddle Inference is not used. The page's crops are read together, `batch_size` 8 per pass (squiddleocr's
`--batch-size` applies to the formula model too).
squiddleocr's alternative (`--formula-model PP-FormulaNet-L`); not exercised in the parity runs.
