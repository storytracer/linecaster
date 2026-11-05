Qianfan-OCR, as the BHL OCR board's driver ran it (built from the card and the checkpoint's config rather than
inherited from Daniel van Strien's `qianfan-ocr.py`).

- The page image, then the card's prompt `Parse this document to Markdown.` (image before text).
- The image bytes as they are, no resize and no conversion, the media type sniffed from the magic bytes: the
  card documents no pixel bounds and the processor tiles and RGB-converts itself (max 12 tiles + a 448-px
  thumbnail). The 60-page sample's lossless WebP decodes to the same pixels as the board's dataset bytes.
- Layout-as-Thought off (`enable_thinking` false per request; the card: disable it for homogeneous pages such
  as book pages).
- Sampling: temperature 0.0 (the card's `do_sample=False`), top_p 1.0, max_tokens 8192.
- Serve flags: `--max-model-len 16384`, one image per prompt, no multimodal processor cache, no prefix caching.
  Not `--trust-remote-code` (the repo ships no code) and not the card's `--hf-overrides` to InternVLChatModel
  (vLLM registers the model natively; the override would run the InternVL code path).
- The completion is stored verbatim; the board's `</think>` strip stays in its harness.
  `--gpu-memory-utilization` is the deployment's choice (board 0.85 on an A10G).

Validated on the 60-page sample (NOTES.md, "Board models as chat specs"): CER reading 0.0482 for linecaster's run on an L4 against 0.0491 for the board's own outputs on the same pages.
