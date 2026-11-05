chandra-ocr-2, as the BHL OCR board's driver ran it: a port of the vendor's own vLLM client, `chandra-ocr`
v0.2.0 (`chandra/model/vllm.py: generate_vllm`) with the `ocr_layout` prompt of the CLI. Where driver and
vendor differ, the driver wins.

- The page image, then the `ocr_layout` prompt (verbatim from `chandra/prompts.py` at v0.2.0, hash-checked as
  the driver does).
- RGB, the vendor's `scale_to_fit` (pixel count clamped to 3072 x 2048 and up to 1792 x 28, both sides snapped
  to multiples of 28, LANCZOS), PNG.
- Sampling: temperature 0.0, top_p 0.1, max_tokens 12384 (the vendor's `MAX_OUTPUT_TOKENS`); the chat template
  opens an empty `<think></think>`, so thinking needs no switch.
- One attempt per page: the vendor client retries a page up to six times at a raised temperature when it
  detects a repetition loop; the board does not, so a loop shows as a loop.
- Serve flags: `--max-model-len 20480` (the board's correction of the vendor's 18000: 6144 visual tokens at the
  cap + 12384 + the prompt do not fit in 18000), the vendor's `--mm-processor-kwargs` pixel bounds and
  `--dtype bfloat16`, one image and no video per prompt, no multimodal processor cache, no prefix caching; no
  `--trust-remote-code`. vLLM 0.26.0 (the vendor's launcher pins 0.17.0).
- The model answers with HTML layout blocks (`<div data-bbox=.. data-label=..>`), stored verbatim; the board
  converts them to Markdown with the vendor's `parse_markdown` in its harness. `--gpu-memory-utilization` is
  the deployment's choice (board 0.8 on an A10G, at most 12 pages in flight).

Validated on the 60-page sample (NOTES.md, "Board models as chat specs"): CER reading 0.0190 for linecaster's run on an L4 against 0.0197 for the board's own outputs on the same pages.
