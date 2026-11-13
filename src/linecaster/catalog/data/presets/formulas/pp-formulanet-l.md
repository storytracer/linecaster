PP-FormulaNet-L on every `formula` region (display formulas; inline formulas are not handled): the region's crop in,
LaTeX out, as a `Formula` of the region. The model runs on PaddleX's transformers engine (Hugging Face
transformers on torch, the same GPU as kraken); the official model source has no ONNX package for any formula
model and Paddle Inference is not used. The page's crops are read together, `batch_size` 8 per pass, the
line recognizer's batch size.
An alternative to `pp-formulanet-plus-l`, the squiddle combination's formula step.
