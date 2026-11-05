PaddleOCR-VL-1.6's VLM alone on the whole page (task mode `ocr`), as the BHL OCR board's driver ran it (a port
of Daniel van Strien's `paddleocr-vl-1.6.py`), not PaddleOCR-VL's PP-DocLayout + VLM pipeline.

- The page image, then the text part `OCR:`.
- RGB, resized client-side by the recipe's `smart_resize`: both sides rounded to multiples of 28, the area
  brought into [28·28·130, 28·28·1280] px (floor when shrinking, ceil when growing; aspect kept), LANCZOS,
  PNG; an image already on that grid is sent unresized (still re-encoded as PNG).
- Temperature 0.0, max_tokens 4096.
- Serve flags: `--max-model-len 8192 --trust-remote-code --enforce-eager --max-num-batched-tokens 16384`, no
  prefix caching, no multimodal processor cache, one image per prompt.
- The completion is stored verbatim; the board's strip stays in its harness.

Validated on the 60-page sample (NOTES.md, "Board models as chat specs"): CER reading 0.0309 for linecaster's run on an L4 against 0.0309 for the board's own outputs on the same pages. Greedy decoding with identical requests
reproduces the board exactly.
