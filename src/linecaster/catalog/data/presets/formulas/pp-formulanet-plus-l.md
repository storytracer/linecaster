PP-FormulaNet_plus-L on every `formula` region (display formulas; inline formulas are not handled): the region's crop in,
LaTeX out, into `region.extra["formula"]`. The model runs on PaddleX's transformers engine (Hugging Face
transformers on torch, the same GPU as kraken); the official model source has no ONNX package for any formula
model and Paddle Inference is not used. The page's crops are read together, `batch_size` 8 per pass (squiddleocr's
`--batch-size` applies to the formula model too).
The squiddle combination's formula step: 29/29 formulas identical to squiddleocr on its formula test pages.
