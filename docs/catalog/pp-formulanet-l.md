# pp-formulanet-l

*Edition 1 · formulas · experimental*

PP-FormulaNet-L on every `formula` region (display formulas; inline formulas are not handled): the region's crop in,
LaTeX out, into `region.extra["formula"]`. The model runs on PaddleX's transformers engine (Hugging Face
transformers on torch, the same GPU as kraken); the official model source has no ONNX package for any formula
model and Paddle Inference is not used. The page's crops are read together, `batch_size` 8 per pass (squiddleocr's
`--batch-size` applies to the formula model too).
squiddleocr's alternative (`--formula-model PP-FormulaNet-L`); not exercised in the parity runs.

| | |
|---|---|
| Step | formulas (reads regions) |
| Engine | `paddlex.formulas/1` |
| Model | [PP-FormulaNet-L](https://huggingface.co/PaddlePaddle/PP-FormulaNet-L_safetensors/tree/69869f2891cc61347d230ef234bcc8b8d297c43a) |
| Revision | `69869f2891cc61347d230ef234bcc8b8d297c43a` |
| Upstream card | [upstream/69869f2891cc61347d230ef234bcc8b8d297c43a/README.md](../../engines/paddlex/src/linecaster_paddlex/catalog/models/pp-formulanet-l-safetensors/upstream/69869f2891cc61347d230ef234bcc8b8d297c43a/README.md) (verbatim, at that revision) |
| Licence | Apache-2.0 |
| Derived from | converted of PaddlePaddle/PP-FormulaNet-L |
| Produces | formulas, latex |

## Provenance

- storytracer/squiddleocr@7c8a052 (the settings its goldens were recorded with: sample-60, tables-7); --formula-model PP-FormulaNet-L
