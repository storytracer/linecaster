dots.mocr in plain OCR mode, following the model card, upstream's `dots_mocr/model/inference.py` server client and
the uv-scripts recipe `dots-mocr.py`.

- Plain OCR only: the prompt `Extract the text content from this image.`; plain text out, no layout JSON.
- The image, then a text part that starts with vLLM's dots placeholder `<|img|><|imgpad|><|endofimg|>`
  followed by the prompt (upstream's server client); with `--chat-template-content-format string` vLLM adds no
  placeholder of its own.
- Full resolution, no resize: RGB PNG/JPEG bytes as they are, anything else RGB PNG (the processor clamps to
  its own `max_pixels` 11289600).
- Sampling from upstream `inference.py`: temperature 0.1, top_p 0.9; max_tokens 16384 (linecaster's choice: a
  full-size page is at most 14400 image tokens, 14400 + 16384 < 32768).
- Serve flags: `--max-model-len 32768 --trust-remote-code --chat-template-content-format string` (the card's
  `vllm serve` line), no prefix caching, no multimodal processor cache, one image per prompt.
- The completion is stored verbatim. vLLM 0.26.0; `--gpu-memory-utilization` is the deployment's choice. Measured
  on an RTX 4000 SFF Ada (NOTES.md, "dots.mocr and LightOnOCR-3 on an RTX 4000 SFF Ada"); experimental.
