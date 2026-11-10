OvisOCR2, following the model card and the uv-scripts recipe `ovis-ocr2-server.py`.

- The page image, then the card's Markdown OCR prompt as a text part. OvisOCR2's prompt starts with a newline (the server recipe's).
- RGB, downscaled with LANCZOS to at most 8,294,400 px (2880 x 2880, the processor's `max_pixels`) and never
  upscaled, then JPEG quality 95 (every image, also when it fits).
- Sampling: temperature 0.0, max_tokens 16384, thinking off per request.
- Serve flags: `--max-model-len 32768`, no prefix caching, no multimodal processor cache, one image per prompt,
  `--mm-processor-kwargs` with the processor's pixel bounds; no `--trust-remote-code`.
- The completion is stored verbatim, `<img src="images/bbox_...">` placeholders and all. The card's
  `clean_truncated_repeats` trimmer is not applied (linecaster's choice: the output stays as the model wrote it).
  `--gpu-memory-utilization` is the deployment's choice.
