LightOnOCR-3-0.8B on whole pages, following the model card (the two LightOnOCR-3 presets differ only in the
checkpoint).

- The page image only, no text part (the card's transcription call; grounding is another output, not run).
- RGB, `thumbnail((2048, 2048))`, PNG: the card's target longest dimension. `thumbnail` only downscales, so a
  smaller page is sent as it is (unlike LightOnOCR-2's forced 1540 px).
- Sampling from the card: temperature 0.2, top_p 0.9, max_tokens 4096; thinking off per request and
  server-side (`--default-chat-template-kwargs`).
- Serve flags: `--max-model-len 18000` (LightOn's README for the 0.8B, and the reference script
  uv-scripts/ocr `lighton-ocr3-saturate.py` at e2b0aa5; a 2048-px page is at most 4096 image tokens), one image and
  no video per prompt, no multimodal processor cache, no prefix caching; no `--trust-remote-code`.
- The repair pass is on, at 12,288 tokens (`settings.repair.max_tokens`): a page whose completion stopped at
  `max_tokens` is sent once more, on demand and only once (two passes at most), with that cap and temperature 0.1
  (`settings.repair.temperature`, the reference script's), and keeps the second completion where it finished
  (`stop`); otherwise the first. 12,288 rather than the reference script's suggested 8192: a dense table page needed
  8,958 tokens, and one needing about 7,960 hit 8192 in one run of three (NOTES.md).
  `--set recognition.repair_max_tokens=0` turns it off. With 18000 tokens of context a repair of up to 13,840 tokens fits beside the largest page prompt
  (4,096 image tokens and 64 for the rest).
- vLLM 0.30.0: LightOn's repository says 0.27.1 makes these models loop. The HF Jobs image is therefore
  `vllm/vllm-openai:v0.30.0`.
- The completion is stored verbatim; `--gpu-memory-utilization` is the deployment's choice. Experimental.

Editions: 1 served with `--max-model-len 16384` (linecaster's choice then); 2 serves with LightOn's 18000, so that a
repair pass has room, and states the repair settings (off); 3 turns the repair pass on at 12,288 tokens.
