GLM-OCR, following the model card and the uv-scripts recipe `glm-ocr.py`.

- The page image, then the card's prompt `Text Recognition:`.
- RGB and, only if its area exceeds the processor's ceiling (`max_pixels` 9633792, `preprocessor_config.json`),
  downscaled by sqrt(max_pixels / area) with the sides truncated to ints, LANCZOS; never upscaled; PNG.
- Temperature 0.01, top_p 1e-05, repetition_penalty 1.1 (the authors' SDK values, via the recipe), max_tokens
  8192 (card).
- Serve flags: `--max-model-len 32768`, no prefix caching, no multimodal processor cache, one image per prompt;
  no `--trust-remote-code` (the architecture is in vLLM). vLLM 0.26.0, a release, where the card uses a nightly
  (linecaster's choice).
- The completion is stored verbatim.
