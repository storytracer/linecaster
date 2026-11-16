LightOnOCR-2-1B on layout regions (`RegionRecognizer` after a layout step): each region is cut from the page
scaled to LightOnOCR's 1540-px page size, 8 px around its box at that scale, and sent as it is, with the page
preset's request and sampling.

LightOnOCR-2 is trained on whole pages, not on region crops. Kept as an experimental way to read regions with a page
model; region reading wants a region-trained model (`minicpm-ocr-1.0`).
- vLLM 0.26.0, the release it was validated on, not linecaster's 0.30.0: 0.30.0's LightOnOCR model imports
  `PixtralRotaryEmbedding`, which the transformers it resolves (5.17) no longer has (2026-11-16, the top-15 run).
