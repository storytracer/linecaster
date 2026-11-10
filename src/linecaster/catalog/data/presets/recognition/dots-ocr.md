dots.ocr in plain OCR mode, following the model card and the uv-scripts recipe `dots-ocr.py`.

- Plain OCR (the card's `prompt_ocr` mode): the prompt `Extract the text content from this image.`; the output is
  plain text, not layout JSON, so there is nothing to convert.
- The image, then the prompt as a text part, with no image placeholder in the text (unlike dots.mocr) and no
  `--chat-template-content-format`.
- Full resolution, no resize: RGB PNG/JPEG bytes as they are, anything else converted to RGB PNG.
- Sampling: temperature 0.0, max_tokens 8192 (no top_p).
- Serve flags: `--max-model-len 32768 --trust-remote-code`, no prefix caching, no multimodal processor cache,
  one image per prompt.
- On a 24 GB card (A10G) the vision encoder ran out of memory at `--gpu-memory-utilization 0.8` with 12 pages in
  flight; 0.6, at most 4 pages in flight and `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` worked. These are
  deployment choices, not part of the preset.
