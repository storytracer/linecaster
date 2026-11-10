chandra-ocr-2 as the vendor's own vLLM client runs it, `chandra-ocr` v0.2.0 (`chandra/model/vllm.py: generate_vllm`),
with the `ocr_layout` prompt of the CLI. Where linecaster departs from the client, the item says so.

- The page image, then the `ocr_layout` prompt (verbatim from `chandra/prompts.py` at v0.2.0, hash-checked).
- RGB, the vendor's `scale_to_fit` (pixel count clamped to 3072 x 2048 and up to 1792 x 28, both sides snapped
  to multiples of 28, LANCZOS), PNG.
- Sampling: temperature 0.0, top_p 0.1, max_tokens 12384 (the vendor's `MAX_OUTPUT_TOKENS`); the chat template
  opens an empty `<think></think>`, so thinking needs no switch.
- One attempt per page (linecaster's choice): the vendor client retries a page up to six times at a raised
  temperature when it detects a repetition loop; here a loop shows as a loop.
- Serve flags: `--max-model-len 20480` (linecaster's choice, where the vendor's launcher has 18000: 6144 visual
  tokens at the cap + 12384 + the prompt do not fit in 18000), the vendor's `--mm-processor-kwargs` pixel bounds
  and `--dtype bfloat16`, one image and no video per prompt, no multimodal processor cache, no prefix caching; no
  `--trust-remote-code`. vLLM 0.26.0 (linecaster's choice; the vendor's launcher pins 0.17.0).
- The model answers with HTML layout blocks (`<div data-bbox=.. data-label=..>`), stored verbatim; converting them
  to Markdown (the vendor's `parse_markdown`) is left to whoever reads the output. `--gpu-memory-utilization` is
  the deployment's choice.

Validated against a reference implementation's outputs on a 60-page sample of historic print (NOTES.md, "Chat
presets: validation on the 60-page sample").
