# pp-formulanet-plus-l

*Edition 1 · formulas · core*

PP-FormulaNet_plus-L on every `formula` region (display formulas; inline formulas are not handled): the region's crop in,
LaTeX out, into `region.extra["formula"]`. The model runs on PaddleX's transformers engine (Hugging Face
transformers on torch, the same GPU as kraken); the official model source has no ONNX package for any formula
model and Paddle Inference is not used. The page's crops are read together, `batch_size` 8 per pass (squiddleocr's
`--batch-size` applies to the formula model too).
The squiddle combination's formula step: 29/29 formulas identical to squiddleocr on its formula test pages.

| | |
|---|---|
| Step | formulas (reads regions) |
| Engine | `paddlex.formulas/1` |
| Model | [PP-FormulaNet_plus-L](https://huggingface.co/PaddlePaddle/PP-FormulaNet_plus-L_safetensors/tree/6cc004a8e91ea3f3819b05317f40b290cbe99c2b) |
| Revision | `6cc004a8e91ea3f3819b05317f40b290cbe99c2b` |
| Upstream card | [upstream/6cc004a8e91ea3f3819b05317f40b290cbe99c2b/README.md](../../engines/paddlex/src/linecaster_paddlex/catalog/models/pp-formulanet-plus-l-safetensors/upstream/6cc004a8e91ea3f3819b05317f40b290cbe99c2b/README.md) (verbatim, at that revision) |
| Licence | Apache-2.0 |
| Derived from | converted of PaddlePaddle/PP-FormulaNet_plus-L |
| Produces | formulas, latex |

## Provenance

- storytracer/squiddleocr@7c8a052 (the settings its goldens were recorded with: sample-60, tables-7)
