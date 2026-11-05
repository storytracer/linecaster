OvisOCR2, as the BHL OCR board's driver ran it (a port of Daniel van Strien's `ovis-ocr2-server.py`; where driver and recipe differ, the driver wins).

- The page image, then the card's Markdown OCR prompt as a text part. OvisOCR2's prompt starts with a newline (the server recipe's).
- RGB, downscaled with LANCZOS to at most 8,294,400 px (2880 x 2880, the processor's `max_pixels`) and never
  upscaled, then JPEG quality 95 (every image, also when it fits).
- Sampling: temperature 0.0, max_tokens 16384, thinking off per request.
- Serve flags: `--max-model-len 32768`, no prefix caching, no multimodal processor cache, one image per prompt,
  `--mm-processor-kwargs` with the processor's pixel bounds; no `--trust-remote-code`.
- The completion is stored verbatim, `<img src="images/bbox_...">` placeholders and all: the board drops those
  blocks in its harness. The card's `clean_truncated_repeats` trimmer is not applied (the board's documented
  deviation). `--gpu-memory-utilization` is the deployment's choice (board 0.8).

Validated on the 60-page sample (NOTES.md, "Board models as chat specs"): CER reading 0.0276 for linecaster's run on an L4 against 0.0274 for the board's own outputs on the same pages.
