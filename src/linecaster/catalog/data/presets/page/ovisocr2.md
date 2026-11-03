---
schema: linecaster.preset/1
id: ovisocr2
edition: 1
step: page
model:
  id: ovisocr2
  revision: 65c619d374b55d4152e85150fc1b003700bc1f0c
engine: chat.v1
options:
  adapter: ovis-ocr
settings:
  sampling:
    temperature: 0.0
    max_tokens: 16384
  prompt: |2-

    Extract all readable content from the image in natural human reading order and output the result as a single Markdown document. For charts or images, represent them using an HTML image tag: <img src="images/bbox_{left}_{top}_{right}_{bottom}.jpg" />, where left, top, right, bottom are bounding box coordinates scaled to [0, 1000). Format formulas as LaTeX. Format tables as HTML: <table>...</table>. Transcribe all other text as standard Markdown. Preserve the original text without translation or paraphrasing.
  chat_template_kwargs:
    enable_thinking: false
  image:
    max_pixels: 8294400
    jpeg_quality: 95
serve:
  server: vllm
  version: 0.26.0
  image: vllm/vllm-openai:v0.26.0
  flags:
  - --max-model-len
  - '32768'
  - --no-enable-prefix-caching
  - --mm-processor-cache-gb
  - '0'
  - --limit-mm-per-prompt
  - '{"image": 1}'
  - --mm-processor-kwargs
  - '{"images_kwargs": {"min_pixels": 200704, "max_pixels": 8294400}}'
capabilities:
  unit: page
  produces:
  - markdown
  - html
provenance:
  derived_from:
  - finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/ovis-ocr2-port.py
  - uv-scripts/ocr@4ae561fcfef053f60c310cd04f7a7fa0e2fadce2:ovis-ocr2-server.py
  - ATH-MaaS/OvisOCR2@65c619d374b55d4152e85150fc1b003700bc1f0c:README.md
  created: 2026-11-03
support: core
---

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
