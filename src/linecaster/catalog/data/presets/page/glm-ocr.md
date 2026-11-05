GLM-OCR, as the BHL OCR board's driver ran it (a port of Daniel van Strien's `glm-ocr.py`).

- The page image, then the card's prompt `Text Recognition:`.
- RGB and, only if its area exceeds the processor's ceiling (`max_pixels` 9633792, `preprocessor_config.json`),
  downscaled by sqrt(max_pixels / area) with the sides truncated to ints, LANCZOS; never upscaled; PNG.
- Temperature 0.01, top_p 1e-05, repetition_penalty 1.1 (the authors' SDK values, via the recipe), max_tokens
  8192 (card).
- Serve flags: `--max-model-len 32768`, no prefix caching, no multimodal processor cache, one image per prompt;
  no `--trust-remote-code` (the architecture is in vLLM). vLLM 0.26.0, the board-wide pin instead of the
  card's nightly.
- The completion is stored verbatim; the board's strip and empty-completion check stay in its harness.

Validated on the 60-page sample (NOTES.md, "Board models as chat specs"): CER reading 0.0368 for linecaster's run on an L4 against 0.0360 for the board's own outputs on the same pages.
