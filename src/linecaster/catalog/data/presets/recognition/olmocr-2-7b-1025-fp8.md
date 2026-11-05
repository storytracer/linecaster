olmOCR-2-7B-1025-FP8, as the BHL OCR board's driver ran it (a port of Daniel van Strien's `olmocr2-vllm.py`;
where the two differ, the driver wins).

- The olmOCR no-anchoring (v4, YAML) prompt as a text part, THEN the page image (text before image, as the
  driver sends it).
- PNG with the longest side forced to exactly 1288 px, up or down (the olmOCR pipeline's
  `target_longest_image_dim`), LANCZOS.
- Sampling: temperature 0.1, max_tokens 8192, repetition_penalty 1.05, stop `<|im_end|>`, `<|endoftext|>` (the
  recipe's values, recorded in the driver).
- Serve flags: `--max-model-len 16384`, no prefix caching, no multimodal processor cache, one image per prompt;
  no `--trust-remote-code`. vLLM 0.26.0 (the board's; Daniel's recipe has since moved to 0.29.0).
- The model answers with YAML front matter (primary_language, is_rotation_valid, rotation_correction, is_table,
  is_diagram) above the page text. The completion is stored verbatim and the front matter also parsed into
  `extra["front_matter"]`; dropping it from the scored text is the board's post-processing, left to the
  harness (`linecaster.adapters.olmocr2.body` gives the same split). Not yet run by linecaster: experimental.
