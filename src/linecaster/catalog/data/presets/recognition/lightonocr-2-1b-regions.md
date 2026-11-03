---
schema: linecaster.preset/1
id: lightonocr-2-1b-regions
edition: 1
step: recognition
model:
  id: lightonocr-2-1b
  revision: c97bd377f04481830395218fa8951df9deaba756
engine: chat.v1
options:
  adapter: lighton-ocr-2
settings:
  sampling:
    max_tokens: 4096
    temperature: 0.2
    top_p: 0.9
  image:
    longest_side_px: 1540
  page_longest: 1540
  region_pad: 8
serve:
  server: vllm
  version: 0.26.0
  image: vllm/vllm-openai:v0.26.0
  flags:
  - --max-model-len
  - '16384'
  - --limit-mm-per-prompt
  - '{"image": 1}'
  - --mm-processor-cache-gb
  - '0'
  - --no-enable-prefix-caching
capabilities:
  unit: region
  produces:
  - markdown
provenance:
  derived_from:
  - finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/lighton-ocr2-port.py
  - uv-scripts/ocr@4ae561fcfef053f60c310cd04f7a7fa0e2fadce2:lighton-ocr2-saturate.py
  - lightonai/LightOnOCR-2-1B@c97bd377f04481830395218fa8951df9deaba756:README.md
  created: 2026-11-03
support: experimental
---

LightOnOCR-2-1B on layout regions (`ChatRegionStep` after a layout step): each region is cut from the page
scaled to LightOnOCR's 1540-px page size, 8 px around its box at that scale, and sent as it is, with the page
preset's request and sampling.

LightOnOCR-2 is trained on whole pages. On the 60-page sample with PP-DocLayoutV3 regions it loops to its token
limit on 68 of 418 region crops (page headers, footers, footnotes); with those regions left empty the reading
CER is 0.0402 against 0.0285 for whole pages (NOTES.md, "Region recognition with a page model"). Kept as an
experimental way to read regions with a page model; region reading wants a region-trained model
(`minicpm-ocr-1.0`).
