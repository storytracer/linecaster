PaddleOCR-VL-1.6's VLM alone on the whole page (task mode `ocr`), following the model card and the uv-scripts
recipe `paddleocr-vl-1.6.py`; not PaddleOCR-VL's PP-DocLayout + VLM pipeline.

- The page image, then the text part `OCR:`.
- RGB, resized client-side by the recipe's `smart_resize`: both sides rounded to multiples of 28, the area
  brought into [28·28·130, 28·28·1280] px (floor when shrinking, ceil when growing; aspect kept), LANCZOS,
  PNG; an image already on that grid is sent unresized (still re-encoded as PNG).
- Temperature 0.0, max_tokens 4096.
- Serve flags: `--max-model-len 8192 --trust-remote-code --enforce-eager --max-num-batched-tokens 16384`, no
  prefix caching, no multimodal processor cache, one image per prompt.
- The completion is stored verbatim.

Validated against a reference implementation's outputs on a 60-page sample of historic print (NOTES.md, "Chat
presets: validation on the 60-page sample"); greedy decoding with identical requests gave identical outputs.
