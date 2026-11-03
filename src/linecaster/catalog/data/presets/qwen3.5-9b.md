---
schema: linecaster.preset/1
id: qwen3.5-9b
edition: 1
step: page
model:
  id: qwen3.5-9b
  revision: c202236235762e1c871ad0ccb60c8ee5ba337b9a
engine:
  kind: chat/1
  options:
    adapter: qwen3.5
settings:
  sampling:
    max_tokens: 8192
    temperature: 0.0
    presence_penalty: 1.5
    repetition_penalty: 1.0
  prompt: Transcribe all of the text in this image.
  prompt_variant: neutral
  chat_template_kwargs:
    enable_thinking: false
  image:
    max_pixels: 2097152
    jpeg_quality: 95
serve:
  server: vllm
  version: 0.26.0
  image: vllm/vllm-openai:v0.26.0
  flags:
  - --max-model-len
  - '16384'
  - --max-num-batched-tokens
  - '16384'
  - --no-enable-prefix-caching
  - --mm-processor-cache-gb
  - '0'
  - --limit-mm-per-prompt
  - '{"image": 1, "video": 0}'
capabilities:
  unit: page
  produces:
  - text
provenance:
  derived_from:
  - finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/qwen35-9b-port.py
  - Qwen/Qwen3.5-9B@c202236235762e1c871ad0ccb60c8ee5ba337b9a:README.md
  created: 2026-11-03
support: core
---

Qwen3.5-9B as a page reader: the BHL OCR board's "greedy + card penalties" row (its driver, written from the
model card and the checkpoint's config, run with `--prompt neutral --card-penalties`; there is no uv-scripts
recipe for this model).

- The page image, then the prompt `Transcribe all of the text in this image.` (the driver's `neutral` variant;
  a house choice, the card documents no OCR prompt). The board names the row by this variant.
- RGB and, only when it has more than 2048 x 1024 px (2048 visual tokens at 1024 px per token), downscaled to
  that area keeping the aspect ratio (`int` truncation, LANCZOS); JPEG quality 95. Smaller pages are not
  upscaled.
- Sampling: greedy (temperature 0.0, the board's deliberate deviation from the card) with the card's penalties
  (presence_penalty 1.5, repetition_penalty 1.0); max_tokens 8192; thinking off per request (the shipped
  template opens a `<think>` block unless `enable_thinking` is false).
- Serve flags: `--max-model-len 16384 --max-num-batched-tokens 16384`, no prefix caching, no multimodal
  processor cache, one image and no video per prompt; no `--reasoning-parser` (the driver drops the card's, so
  the completion stays in `content`), no `--trust-remote-code`.
- The completion is stored verbatim; the board's `unwrap_fence` stays in its harness
  (`linecaster.models.qwen35.unwrap_fence` is the same rule).
- Memory: 18.0 GiB of bf16 weights. The board ran it on an L40S at 0.9; whether it fits a 24 GB card (L4,
  A10G) with room for the vision encoder and the KV cache is not tested.

Validated on the 60-page sample (NOTES.md, "Board models as chat specs"): CER reading 0.0358 for linecaster's run on an L40S against 0.0356 for the board's own outputs on the same pages.
