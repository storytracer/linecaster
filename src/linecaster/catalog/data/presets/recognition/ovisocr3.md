OvisOCR3, following its model card: the OvisOCR2 preset with the model, its pinned revision and the prompt file of the
OvisOCR3 card; every other value identical.

- The page image, then the card's Markdown OCR prompt as a text part. The prompt is `prompts/document_markdown.txt`
  from the model repo at the pinned revision: OvisOCR2's text without the leading newline. The OvisOCR3 card runs
  vLLM 0.22.1 with `gdn_prefill_backend="triton"`; the preset leaves vLLM's default backend (linecaster's
  choice), and vLLM may pick another default GDN prefill backend on other GPUs (Qwen3.5 base), so compare outputs at
  CER level.
- RGB, downscaled with LANCZOS to at most 8,294,400 px (2880 x 2880, the processor's `max_pixels`) and never
  upscaled, then JPEG quality 95 (every image, also when it fits).
- Sampling: temperature 0.0, max_tokens 16384, thinking off per request.
- Serve flags: `--max-model-len 32768`, no prefix caching, no multimodal processor cache, one image per prompt,
  `--mm-processor-kwargs` with the processor's pixel bounds; no `--trust-remote-code`.
- The completion is stored verbatim, `<img src="images/bbox_...">` placeholders and all. The card's
  `clean_truncated_repeats` trimmer is not applied (linecaster's choice: the output stays as the model wrote it).
  `--gpu-memory-utilization` is the deployment's choice.
