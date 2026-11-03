---
schema: linecaster.preset/1
id: lightonocr-3-4b
edition: 1
step: page
model:
  id: lightonocr-3-4b
  revision: b71010f095dc3735de7ee6b9969bff8f8f50b39a
engine: chat.v1
options:
  adapter: lighton-ocr-3
settings:
  sampling:
    max_tokens: 4096
    temperature: 0.2
    top_p: 0.9
  chat_template_kwargs:
    enable_thinking: false
  image:
    longest_side_px: 2048
  page_longest: 2048
serve:
  server: vllm
  version: 0.30.0
  image: vllm/vllm-openai:v0.30.0
  flags:
  - --max-model-len
  - '16384'
  - --default-chat-template-kwargs
  - '{"enable_thinking": false}'
  - --limit-mm-per-prompt
  - '{"image": 1, "video": 0}'
  - --mm-processor-cache-gb
  - '0'
  - --no-enable-prefix-caching
capabilities:
  unit: page
  produces:
  - markdown
provenance:
  derived_from:
  - finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/lighton-ocr3-port.py
  - lightonai/LightOnOCR-3-4B@b71010f095dc3735de7ee6b9969bff8f8f50b39a:README.md
  created: 2026-11-03
support: experimental
---

LightOnOCR-3-4B on whole pages, as the BHL OCR board ran it (one driver for both LightOnOCR-3 rows,
following the model card; the two presets differ only in the checkpoint).

- The page image only, no text part (the card's transcription call; grounding is another output, not run).
- RGB, `thumbnail((2048, 2048))`, PNG: the card's target longest dimension. `thumbnail` only downscales, so a
  smaller page is sent as it is (unlike LightOnOCR-2's forced 1540 px).
- Sampling from the card: temperature 0.2, top_p 0.9, max_tokens 4096; thinking off per request and
  server-side (`--default-chat-template-kwargs`).
- Serve flags: `--max-model-len 16384` (the board's; a 2048-px page is at most 4096 image tokens), one image
  and no video per prompt, no multimodal processor cache, no prefix caching; no `--trust-remote-code`.
- vLLM 0.30.0, not the board-wide 0.26.0: LightOn's repository says 0.27.1 makes these models loop. The HF
  Jobs image is therefore `vllm/vllm-openai:v0.30.0` (the recipe ran these on 0.26.0 before the presets).
- The completion is stored verbatim; `--gpu-memory-utilization` is the deployment's choice (board 0.8 on an
  A10G). Not yet run by linecaster: experimental.
