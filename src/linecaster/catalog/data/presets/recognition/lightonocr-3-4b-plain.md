LightOnOCR-3-4B in its plain mode on whole pages (the model card's transcription call; LightOn's CLI calls it
`--mode plain`): the page as Markdown, furniture unlabelled in the text. linecaster's default for LightOnOCR-3 is
grounding mode (`lightonocr-3-4b`); this preset was `lightonocr-3-4b` until linecaster 0.10.4. The two
plain presets differ only in the checkpoint.

- The page image only, no text part (grounding is `lightonocr-3-4b`).
- RGB, `thumbnail((2048, 2048))`, PNG: the card's target longest dimension. `thumbnail` only downscales, so a
  smaller page is sent as it is (unlike LightOnOCR-2's forced 1540 px).
- Sampling from the card: temperature 0.2, top_p 0.9, max_tokens 4096; thinking off per request and
  server-side (`--default-chat-template-kwargs`).
- Serve flags: `--max-model-len 16384` (linecaster's choice; a 2048-px page is at most 4096 image tokens), one
  image and no video per prompt, no multimodal processor cache, no prefix caching; no `--trust-remote-code`.
- linecaster's vLLM, 0.30.0 or later: LightOn's repository says 0.27.1 makes these models loop.
- The completion is stored verbatim; `--gpu-memory-utilization` is the deployment's choice. Experimental.
