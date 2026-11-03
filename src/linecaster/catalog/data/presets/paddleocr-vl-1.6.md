---
schema: linecaster.preset/1
id: paddleocr-vl-1.6
edition: 1
step: page
model:
  id: paddleocr-vl-1.6
  revision: 66317acc4c9fc17bd154591ce650735cd2855f3e
engine:
  kind: chat/1
  options:
    adapter: paddleocr-vl
settings:
  sampling:
    temperature: 0.0
    max_tokens: 4096
  prompt: 'OCR:'
  image:
    factor: 28
    min_pixels: 101920
    max_pixels: 1003520
serve:
  server: vllm
  version: 0.26.0
  image: vllm/vllm-openai:v0.26.0
  flags:
  - --max-model-len
  - '8192'
  - --trust-remote-code
  - --enforce-eager
  - --max-num-batched-tokens
  - '16384'
  - --no-enable-prefix-caching
  - --mm-processor-cache-gb
  - '0'
  - --limit-mm-per-prompt
  - '{"image": 1}'
capabilities:
  unit: page
  produces:
  - text
provenance:
  derived_from:
  - finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/paddleocr-vl-16-port.py
  - uv-scripts/ocr@4ae561fcfef053f60c310cd04f7a7fa0e2fadce2:paddleocr-vl-1.6.py
  - PaddlePaddle/PaddleOCR-VL-1.6@66317acc4c9fc17bd154591ce650735cd2855f3e:README.md
  created: 2026-11-03
support: core
---

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
