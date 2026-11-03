---
schema: linecaster.preset/1
id: glm-ocr
edition: 1
step: page
model:
  id: glm-ocr
  revision: ca5d8b3e287e52589e37c28385d9655ee4372f9d
engine: chat.v1
options:
  adapter: glm-ocr
settings:
  sampling:
    temperature: 0.01
    top_p: 1.0e-05
    repetition_penalty: 1.1
    max_tokens: 8192
  prompt: 'Text Recognition:'
  image:
    max_pixels: 9633792
serve:
  server: vllm
  version: 0.26.0
  image: vllm/vllm-openai:v0.26.0
  flags:
  - --max-model-len
  - '32768'
  - --no-enable-prefix-caching
  - --mm-processor-cache-gb
  - '0'
  - --limit-mm-per-prompt
  - '{"image": 1}'
capabilities:
  unit: page
  produces:
  - text
provenance:
  derived_from:
  - finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/glm-ocr-port.py
  - uv-scripts/ocr@4ae561fcfef053f60c310cd04f7a7fa0e2fadce2:glm-ocr.py
  - zai-org/GLM-OCR@ca5d8b3e287e52589e37c28385d9655ee4372f9d:README.md
  created: 2026-11-03
support: core
---

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
