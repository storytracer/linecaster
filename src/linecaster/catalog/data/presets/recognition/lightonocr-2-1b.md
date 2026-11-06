LightOnOCR-2-1B on whole pages, exactly as the BHL OCR board's saturate driver ran it (a port of Daniel van
Strien's `lighton-ocr2-saturate.py`).

- The page image only, no text part: LightOnOCR-2's trained format, per the card.
- PNG with the longest side forced to exactly 1540 px, up or down (the card's target longest dimension;
  `processor_config` longest_edge 1540).
- Sampling from the card: temperature 0.2, top_p 0.9, max_tokens 4096.
- Serve flags: the card's three (one image per prompt, no multimodal processor cache, no prefix caching) plus
  `--max-model-len 16384` (the board's; the model's native context). No `--trust-remote-code`: the
  architecture is registered in vLLM.
- The completion is stored verbatim; the board's strip stays in its harness. `--gpu-memory-utilization` is
  the deployment's choice (board 0.8 on an A10G).

Measured on vLLM 0.21.0 rather than the board's 0.26.0, next to the board's own outputs (the evidence, from NOTES.md,
"Chat VLMs: LightOnOCR-2-1B through PageRecognizer"); sampling at temperature 0.2 makes runs differ. Experimental:
not part of the board validation table on 0.26.0.
