LightOnOCR-3-0.8B on whole pages, following the model card (the two LightOnOCR-3 presets differ only in the
checkpoint).

- The page image only, no text part (the card's transcription call; grounding is another output, not run).
- RGB, `thumbnail((2048, 2048))`, PNG: the card's target longest dimension. `thumbnail` only downscales, so a
  smaller page is sent as it is (unlike LightOnOCR-2's forced 1540 px).
- Sampling from the card: temperature 0.2, top_p 0.9, max_tokens 4096; thinking off per request and
  server-side (`--default-chat-template-kwargs`).
- Serve flags: `--max-model-len 16384` (linecaster's choice; a 2048-px page is at most 4096 image tokens), one
  image and no video per prompt, no multimodal processor cache, no prefix caching; no `--trust-remote-code`.
- vLLM 0.30.0: LightOn's repository says 0.27.1 makes these models loop. The HF Jobs image is therefore
  `vllm/vllm-openai:v0.30.0`.
- The completion is stored verbatim; `--gpu-memory-utilization` is the deployment's choice. Experimental.
