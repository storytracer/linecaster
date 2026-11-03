---
schema: linecaster.preset/1
id: unlimited-ocr
edition: 1
step: page
model:
  id: unlimited-ocr
  revision: 07dea832e22aefee32ad281d4b80551282e1c168
engine: chat.v1
options:
  adapter: unlimited-ocr
settings:
  sampling:
    temperature: 0.0
    max_tokens: 8192
    skip_special_tokens: false
  prompt: document parsing.
  vllm_xargs:
    ngram_size: 35
    window_size: 128
  logits_processor: vllm.model_executor.models.unlimited_ocr:NGramPerReqLogitsProcessor
serve:
  server: vllm
  version: 0.26.0
  image: vllm/vllm-openai:v0.26.0
  flags:
  - --max-model-len
  - '32768'
  - --trust-remote-code
  - --no-enable-prefix-caching
  - --mm-processor-cache-gb
  - '0'
  - --limit-mm-per-prompt
  - '{"image": 1}'
capabilities:
  unit: page
  produces:
  - markdown
provenance:
  derived_from:
  - finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/unlimited-ocr-port.py
  - uv-scripts/ocr@4ae561fcfef053f60c310cd04f7a7fa0e2fadce2:unlimited-ocr-vllm.py
  - baidu/Unlimited-OCR@07dea832e22aefee32ad281d4b80551282e1c168:README.md
  created: 2026-11-03
support: core
---

Unlimited-OCR on vLLM, as the BHL OCR board's driver ran it.

- The image, then the text part `document parsing.` (the card's `<image>document parsing.` minus the image
  token: over `/chat/completions` the image is its own content part).
- Full resolution, no resize (the gundam crop grid is chosen from the input pixels): RGB PNG/JPEG bytes as
  they are, anything else RGB PNG.
- Temperature 0.0, max_tokens 8192, `skip_special_tokens` false (the grounding tags must survive), and the
  card's no-repeat n-gram guard per request (`vllm_xargs`, the single-image setting) with its logits processor
  registered at boot, last on the command line as the driver keeps it.
- Serve flags: `--max-model-len 32768 --trust-remote-code`, no prefix caching, no multimodal processor cache,
  one image per prompt. vLLM 0.26.0: the card's dedicated `vllm/vllm-openai:unlimited-ocr` image is obsolete,
  the architecture is registered.
- The completion (grounded output, `<|det|>type [bbox]<|/det|>` headers) is stored verbatim; the board's rule
  for this model stays in its harness. A response without content is an error, not an empty page.

Validated on the 60-page sample (NOTES.md, "Board models as chat specs"): CER reading 0.0429 for linecaster's run on an L4 against 0.0449 for the board's own outputs on the same pages.
