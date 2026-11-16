LightOnOCR-3-0.8B in its plain mode on whole pages (the model card's transcription call; LightOn's CLI calls it
`--mode plain`): the page as Markdown, furniture unlabelled in the text. linecaster's default for LightOnOCR-3 is
grounding mode (`lightonocr-3-0.8b`); this preset was `lightonocr-3-0.8b` until linecaster 0.10.4. The two
plain presets differ only in the checkpoint.

- The page image only, no text part (grounding is `lightonocr-3-0.8b`).
- RGB, `thumbnail((2048, 2048))`, PNG: the card's target longest dimension. `thumbnail` only downscales, so a
  smaller page is sent as it is (unlike LightOnOCR-2's forced 1540 px).
- Sampling from the card: temperature 0.2, top_p 0.9, max_tokens 4096; thinking off per request and
  server-side (`--default-chat-template-kwargs`).
- Serve flags: `--max-model-len 18000` (LightOn's README for the 0.8B, and the reference script
  uv-scripts/ocr `lighton-ocr3-saturate.py` at e2b0aa5; a 2048-px page is at most 4096 image tokens), one image and
  no video per prompt, no multimodal processor cache, no prefix caching; no `--trust-remote-code`.
- Repair passes on demand (`settings.repair.max_tokens: [8192, 12288]`, twice and three times the first 4096): a
  page whose completion stopped at `max_tokens` is sent again at 8192 tokens, and, if that stops at its cap too, at
  12,288; never more (three passes at most). Temperature 0.1 (`settings.repair.temperature`, the reference script's);
  the same image, prompt and `top_p`. The page keeps the first completion that finished (`stop`), otherwise its first
  one. The second repair is linecaster's addition to the reference script's one; CHANGELOG.md names the evidence.
  `--set recognition.repair_max_tokens=0` turns the passes off.
- linecaster's vLLM, 0.30.0 or later: LightOn's repository says 0.27.1 makes these models loop.
- The completion is stored verbatim; `--gpu-memory-utilization` is the deployment's choice. Experimental.

Editions: 1 served with `--max-model-len 16384` (linecaster's choice then); 2 serves with LightOn's 18000, so that a
repair pass has room, and states the repair settings (off); 3 turns the repair passes on at 8192 and 12,288 tokens.
