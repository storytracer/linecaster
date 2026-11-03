---
schema: linecaster.preset/1
id: chandra-ocr-2
edition: 1
step: page
model:
  id: chandra-ocr-2
  revision: af93b47dba1b47b6640c86ccf487ed2260ab9a09
engine:
  kind: chat/1
  options:
    adapter: chandra-ocr
settings:
  sampling:
    temperature: 0.0
    top_p: 0.1
    max_tokens: 12384
  prompt: |-
    OCR this image to HTML, arranged as layout blocks.  Each layout block should be a div with the data-bbox attribute representing the bounding box of the block in x0 y0 x1 y1 format.  Bboxes are normalized 0-1000. The data-label attribute is the label for the block.

    Use the following labels:
    - Caption
    - Footnote
    - Equation-Block
    - List-Group
    - Page-Header
    - Page-Footer
    - Image
    - Section-Header
    - Table
    - Text
    - Complex-Block
    - Code-Block
    - Form
    - Table-Of-Contents
    - Figure
    - Chemical-Block
    - Diagram
    - Bibliography
    - Blank-Page

    Only use these tags ['math', 'br', 'i', 'b', 'u', 'del', 'sup', 'sub', 'table', 'tr', 'td', 'p', 'th', 'div', 'pre', 'h1', 'h2', 'h3', 'h4', 'h5', 'ul', 'ol', 'li', 'input', 'a', 'span', 'img', 'hr', 'tbody', 'small', 'caption', 'strong', 'thead', 'big', 'code', 'chem'], and these attributes ['class', 'colspan', 'rowspan', 'display', 'checked', 'type', 'border', 'value', 'style', 'href', 'alt', 'align', 'data-bbox', 'data-label'].

    Guidelines:
    * Inline math: Surround math with <math>...</math> tags. Math expressions should be rendered in KaTeX-compatible LaTeX. Use display for block math.
    * Tables: Use colspan and rowspan attributes to match table structure.
    * Formatting: Maintain consistent formatting with the image, including spacing, indentation, subscripts/superscripts, and special characters.
    * Images: Include a description of any images in the alt attribute of an <img> tag. Do not fill out the src property. Describe in detail inside the div tag. Also convert charts to high fidelity data, and convert diagrams to mermaid.
    * Forms: Mark checkboxes and radio buttons properly.
    * Text: join lines together properly into paragraphs using <p>...</p> tags.  Use <br> tags for line breaks within paragraphs, but only when absolutely necessary to maintain meaning.
    * Chemistry: Use <chem>...</chem> tags for chemical formulas with reactive SMILES.
    * Lists: Preserve indents and proper list markers.
    * Use the simplest possible HTML structure that accurately represents the content of the block.
    * Make sure the text is accurate and easy for a human to read and interpret.  Reading order should be correct and natural.
  prompt_sha256: sha256:025935f3e1de1acdfadd4c7d581ab17eb82e8caaffef7b64962621c80b7ca9a8
  image:
    max_size:
    - 3072
    - 2048
    min_size:
    - 1792
    - 28
    grid: 28
serve:
  server: vllm
  version: 0.26.0
  image: vllm/vllm-openai:v0.26.0
  flags:
  - --max-model-len
  - '20480'
  - --mm-processor-kwargs
  - '{"min_pixels": 3136, "max_pixels": 6291456}'
  - --limit-mm-per-prompt
  - '{"image": 1, "video": 0}'
  - --mm-processor-cache-gb
  - '0'
  - --no-enable-prefix-caching
  - --dtype
  - bfloat16
capabilities:
  unit: page
  produces:
  - html
provenance:
  derived_from:
  - finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/chandra-ocr2-port.py
  - github.com/datalab-to/chandra@497dfd38d7625259307c81c979d44093e9f75f44 (v0.2.0):chandra/model/vllm.py
  - datalab-to/chandra-ocr-2@af93b47dba1b47b6640c86ccf487ed2260ab9a09:README.md
  created: 2026-11-03
support: core
---

chandra-ocr-2, as the BHL OCR board's driver ran it: a port of the vendor's own vLLM client, `chandra-ocr`
v0.2.0 (`chandra/model/vllm.py: generate_vllm`) with the `ocr_layout` prompt of the CLI. Where driver and
vendor differ, the driver wins.

- The page image, then the `ocr_layout` prompt (verbatim from `chandra/prompts.py` at v0.2.0, hash-checked as
  the driver does).
- RGB, the vendor's `scale_to_fit` (pixel count clamped to 3072 x 2048 and up to 1792 x 28, both sides snapped
  to multiples of 28, LANCZOS), PNG.
- Sampling: temperature 0.0, top_p 0.1, max_tokens 12384 (the vendor's `MAX_OUTPUT_TOKENS`); the chat template
  opens an empty `<think></think>`, so thinking needs no switch.
- One attempt per page: the vendor client retries a page up to six times at a raised temperature when it
  detects a repetition loop; the board does not, so a loop shows as a loop.
- Serve flags: `--max-model-len 20480` (the board's correction of the vendor's 18000: 6144 visual tokens at the
  cap + 12384 + the prompt do not fit in 18000), the vendor's `--mm-processor-kwargs` pixel bounds and
  `--dtype bfloat16`, one image and no video per prompt, no multimodal processor cache, no prefix caching; no
  `--trust-remote-code`. vLLM 0.26.0 (the vendor's launcher pins 0.17.0).
- The model answers with HTML layout blocks (`<div data-bbox=.. data-label=..>`), stored verbatim; the board
  converts them to Markdown with the vendor's `parse_markdown` in its harness. `--gpu-memory-utilization` is
  the deployment's choice (board 0.8 on an A10G, at most 12 pages in flight).

Validated on the 60-page sample (NOTES.md, "Board models as chat specs"): CER reading 0.0190 for linecaster's run on an L4 against 0.0197 for the board's own outputs on the same pages.
