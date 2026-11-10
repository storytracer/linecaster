Qianfan-OCR, built from the model card and the checkpoint's config.

- The page image, then the card's prompt `Parse this document to Markdown.` (image before text).
- The image bytes as they are, no resize and no conversion, the media type sniffed from the magic bytes: the
  card documents no pixel bounds and the processor tiles and RGB-converts itself (max 12 tiles + a 448-px
  thumbnail). Lossless WebP decodes to the same pixels as the source image.
- Layout-as-Thought off (`enable_thinking` false per request; the card: disable it for homogeneous pages such
  as book pages).
- Sampling: temperature 0.0 (the card's `do_sample=False`), top_p 1.0, max_tokens 8192.
- Serve flags: `--max-model-len 16384`, one image per prompt, no multimodal processor cache, no prefix caching.
  Not `--trust-remote-code` (the repo ships no code) and not the card's `--hf-overrides` to InternVLChatModel
  (linecaster's choice: vLLM registers the model natively; the override would run the InternVL code path).
- The completion is stored verbatim, a `</think>` the model may leave included. `--gpu-memory-utilization` is the
  deployment's choice.
