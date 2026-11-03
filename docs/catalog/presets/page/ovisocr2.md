# ovisocr2

*Preset · edition 1 · page · core*

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

|  |  |
|---|---|
| Step | page (reads pages) |
| Engine | [`chat.v1`](../../engines/chat.v1.md) |
| Model | [OvisOCR2](../../models/ovisocr2.md) |
| Revision | [`65c619d374b55d4152e85150fc1b003700bc1f0c`](https://huggingface.co/ATH-MaaS/OvisOCR2/tree/65c619d374b55d4152e85150fc1b003700bc1f0c) |
| Licence | Apache-2.0 |
| Server | vllm 0.26.0 |
| Image | `vllm/vllm-openai:v0.26.0` |
| Produces | markdown, html |

## Options

| Option | Value |
|---|---|
| adapter | `ovis-ocr` |

## Evidence

| Date | Source | Dataset | Result |
|---|---|---|---|
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_reading 0.0276 |
| 2026-11-03 | BHL board | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_reading 0.0274 |

## Provenance

- finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/ovis-ocr2-port.py
- uv-scripts/ocr@4ae561fcfef053f60c310cd04f7a7fa0e2fadce2:ovis-ocr2-server.py
- ATH-MaaS/OvisOCR2@65c619d374b55d4152e85150fc1b003700bc1f0c:README.md
