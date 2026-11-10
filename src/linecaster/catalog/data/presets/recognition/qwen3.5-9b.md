Qwen3.5-9B as a page reader, built from the model card and the checkpoint's config: greedy decoding with the card's
penalties.

- The page image, then the prompt `Transcribe all of the text in this image.` (linecaster's choice, a neutral
  prompt: the card documents no OCR prompt).
- RGB and, only when it has more than 2048 x 1024 px (2048 visual tokens at 1024 px per token), downscaled to
  that area keeping the aspect ratio (`int` truncation, LANCZOS); JPEG quality 95. Smaller pages are not
  upscaled.
- Sampling: greedy (temperature 0.0, linecaster's choice where the card samples) with the card's penalties
  (presence_penalty 1.5, repetition_penalty 1.0); max_tokens 8192; thinking off per request (the shipped
  template opens a `<think>` block unless `enable_thinking` is false).
- Serve flags: `--max-model-len 16384 --max-num-batched-tokens 16384`, no prefix caching, no multimodal
  processor cache, one image and no video per prompt; no `--reasoning-parser` (linecaster's choice, where the card
  has one: the completion stays in `content`), no `--trust-remote-code`.
- The completion is stored verbatim; `linecaster.adapters.qwen35.unwrap_fence` removes a Markdown fence around it.
- Memory: 18.0 GiB of bf16 weights. It runs on a 48 GB card (L40S) at `--gpu-memory-utilization` 0.9; whether it
  fits a 24 GB card (L4, A10G) with room for the vision encoder and the KV cache is not tested.

Validated against a reference implementation's outputs on a 60-page sample of historic print, on an L40S
(NOTES.md, "Chat presets: validation on the 60-page sample").
