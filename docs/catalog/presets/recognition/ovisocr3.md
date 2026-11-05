# ovisocr3

*Preset · edition 1 · recognition · core*

OvisOCR3, as the BHL OCR board's driver ran it (the OvisOCR2 driver with the model, its pinned revision and the prompt file of the OvisOCR3 card; every other value identical).

- The page image, then the card's Markdown OCR prompt as a text part. The prompt is `prompts/document_markdown.txt` from the model repo at the pinned revision: OvisOCR2's text without the leading newline. The OvisOCR3 card runs vLLM 0.22.1 with `gdn_prefill_backend="triton"`, the board the default backend; the board ran it on an A100, and on an L4 vLLM may pick another default GDN prefill backend (Qwen3.5 base), so compare at CER level.
- RGB, downscaled with LANCZOS to at most 8,294,400 px (2880 x 2880, the processor's `max_pixels`) and never
  upscaled, then JPEG quality 95 (every image, also when it fits).
- Sampling: temperature 0.0, max_tokens 16384, thinking off per request.
- Serve flags: `--max-model-len 32768`, no prefix caching, no multimodal processor cache, one image per prompt,
  `--mm-processor-kwargs` with the processor's pixel bounds; no `--trust-remote-code`.
- The completion is stored verbatim, `<img src="images/bbox_...">` placeholders and all: the board drops those
  blocks in its harness. The card's `clean_truncated_repeats` trimmer is not applied (the board's documented
  deviation). `--gpu-memory-utilization` is the deployment's choice (board 0.8).

Validated on the 60-page sample (NOTES.md, "Board models as chat specs"): CER reading 0.0299 for linecaster's run on an L4 against 0.0325 for the board's own outputs on the same pages.

```bash
uv run launch.py ovisocr3 IMAGES OUT
```

|  |  |
|---|---|
| Step | recognition (reads pages) |
| Engine | [`chat.v1`](../../engines/chat.v1.md) |
| Model | [OvisOCR3](../../models/ovisocr3.md) |
| Revision | [`5f6ce6932efee9ec10c30746db55bd780214b7fd`](https://huggingface.co/ATH-MaaS/OvisOCR3/tree/5f6ce6932efee9ec10c30746db55bd780214b7fd) |
| License | Apache-2.0 |
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
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_reading 0.0299 |
| 2026-11-03 | BHL board | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_reading 0.0325 |

## Provenance

- finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/ovis-ocr3-port.py
- ATH-MaaS/OvisOCR3@5f6ce6932efee9ec10c30746db55bd780214b7fd:README.md
