dots.ocr in plain OCR mode, as the BHL OCR board's driver ran it (a port of Daniel van Strien's `dots-ocr.py`;
where the two differ, the driver wins).

- Plain OCR (`--prompt-mode ocr`): the prompt `Extract the text content from this image.`; the output is plain
  text, not layout JSON, so there is nothing to convert.
- The image, then the prompt as a text part, with no image placeholder in the text (unlike dots.mocr) and no
  `--chat-template-content-format`.
- Full resolution, no resize: RGB PNG/JPEG bytes as they are, anything else converted to RGB PNG.
- Sampling: temperature 0.0, max_tokens 8192 (no top_p).
- Serve flags: `--max-model-len 32768 --trust-remote-code`, no prefix caching, no multimodal processor cache,
  one image per prompt.
- The scored board row ran with `--gpu-memory-utilization 0.6`, at most 4 pages in flight and
  `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` on an A10G (0.8 and 12 in flight ran out of memory in the
  vision encoder): deployment choices, not part of the preset.

Validated on the 60-page sample (NOTES.md, "Board models as chat specs"): CER reading 0.0170 for linecaster's run on an L4 against 0.0170 for the board's own outputs on the same pages. Greedy decoding with identical requests
reproduces the board exactly.
