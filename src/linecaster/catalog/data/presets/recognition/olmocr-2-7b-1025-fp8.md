olmOCR-2-7B-1025-FP8, following the model card, the olmOCR pipeline and the uv-scripts recipe `olmocr2-vllm.py`.

- The olmOCR no-anchoring (v4, YAML) prompt as a text part, THEN the page image (text before image, as the
  recipe sends it).
- PNG with the longest side forced to exactly 1288 px, up or down (the olmOCR pipeline's
  `target_longest_image_dim`), LANCZOS.
- Sampling: temperature 0.1, max_tokens 8192, repetition_penalty 1.05, stop `<|im_end|>`, `<|endoftext|>` (the
  recipe's values).
- Serve flags: `--max-model-len 16384`, no prefix caching, no multimodal processor cache, one image per prompt;
  no `--trust-remote-code`. vLLM 0.26.0 (linecaster's choice; the recipe has since moved to 0.29.0).
- The model answers with YAML front matter (primary_language, is_rotation_valid, rotation_correction, is_table,
  is_diagram) above the page text. The completion is stored verbatim and the front matter also parsed into
  `extra["front_matter"]`; `linecaster.adapters.olmocr2.body` gives the page text without it.
  Experimental.
