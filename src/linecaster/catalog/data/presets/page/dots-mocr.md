dots.mocr in plain OCR mode, as the BHL OCR board's driver ran it (a port of Daniel van Strien's
`dots-mocr.py`; where the two differ, the driver wins).

- Plain OCR only: the prompt `Extract the text content from this image.`; plain text out, no layout JSON.
- The image, then a text part that starts with vLLM's dots placeholder `<|img|><|imgpad|><|endofimg|>`
  followed by the prompt (upstream's `dots_mocr/model/inference.py` server client); with
  `--chat-template-content-format string` vLLM adds no placeholder of its own.
- Full resolution, no resize: RGB PNG/JPEG bytes as they are, anything else RGB PNG (the processor clamps to
  its own `max_pixels` 11289600).
- Sampling from upstream `inference.py`: temperature 0.1, top_p 0.9; max_tokens 16384 (the driver's: a
  full-size page is at most 14400 image tokens, 14400 + 16384 < 32768).
- Serve flags: `--max-model-len 32768 --trust-remote-code --chat-template-content-format string` (the card's
  `vllm serve` line), no prefix caching, no multimodal processor cache, one image per prompt.
- The completion is stored verbatim; the board's strip and empty-completion check stay in its harness. The
  board ran vLLM 0.26.0 (Daniel's recipe has moved to 0.29.0); `--gpu-memory-utilization` is the
  deployment's choice (board 0.6 on an L40S, 4 pages in flight). Not yet run by linecaster: experimental.
