SmolDocling-256M-preview, following the model card and the uv-scripts recipe `smoldocling-ocr.py`. The repository
is now `docling-project/SmolDocling-256M-preview`; linecaster pins the id it was published under,
`ds4sd/SmolDocling-256M-preview`.

- The page image FIRST, then `Convert this page to docling.` (the card's chat example). The order matters: the
  repo's chat template branches on `content[0]['type'] == 'image'`.
- RGB, downscaled (never upscaled) so its longest side is at most 2048 px (LANCZOS; the processor's own
  `size.longest_edge`, so only the payload shrinks), JPEG quality 95.
- Sampling: temperature 0.0, max_tokens 6144 (linecaster's choice, not the card's 8192: the native context is
  8192 and an image takes up to about 1600 tokens), `skip_special_tokens` false (DocTags' `<doctag>` and
  `<loc_*>` are added special tokens; vLLM's default strips them).
- Serve flags: `--max-model-len 8192` (`max_position_embeddings`, not raisable), no prefix caching, no
  multimodal processor cache, one image per prompt; no `--trust-remote-code` (Idefics3 is registered in vLLM).
- The model answers in DocTags. The completion is stored verbatim (the transcription's raw output); `parse` also
  converts it with docling-core (body + furniture, no image placeholder) into the transcription's extension field
  `smoldocling__markdown`.
