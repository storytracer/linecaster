LightOnOCR-2-1B on whole pages, following the model card and the uv-scripts recipe `lighton-ocr2-saturate.py`.

- The page image only, no text part: LightOnOCR-2's trained format, per the card.
- PNG with the longest side forced to exactly 1540 px, up or down (the card's target longest dimension;
  `processor_config` longest_edge 1540).
- Sampling from the card: temperature 0.2, top_p 0.9, max_tokens 4096.
- Serve flags: the card's three (one image per prompt, no multimodal processor cache, no prefix caching) plus
  `--max-model-len 16384` (linecaster's choice; the model's native context). No `--trust-remote-code`: the
  architecture is registered in vLLM.
- The completion is stored verbatim. `--gpu-memory-utilization` is the deployment's choice.

Sampling at temperature 0.2 makes runs differ. Experimental.
