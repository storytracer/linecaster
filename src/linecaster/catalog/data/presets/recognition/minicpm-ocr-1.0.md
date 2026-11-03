---
schema: linecaster.preset/1
id: minicpm-ocr-1.0
edition: 1
step: recognition
model:
  id: minicpm-ocr-1.0
  revision: a59a4acf215e34c6d73149e9eafdb88ed2086e39
engine: chat.v1
options:
  adapter: minicpm-ocr
  served_name: minicpm-ocr
settings:
  sampling:
    temperature: 0.01
    top_p: 0.001
    top_k: 1
    repetition_penalty: 1.0
    no_repeat_ngram_size: 100
  mm_processor_kwargs:
    downsample_mode: 4x
    max_slice_nums: 9
  chat_template_kwargs:
    enable_thinking: false
  elements:
    text:
      prompt: 'Text Recognition:'
      max_new_tokens: 4096
      output_format: text
    content:
      prompt: 'Text Recognition:'
      max_new_tokens: 4096
      output_format: text
    abstract:
      prompt: 'Text Recognition:'
      max_new_tokens: 4096
      output_format: text
    reference:
      prompt: 'Text Recognition:'
      max_new_tokens: 2048
      output_format: text
    reference_content:
      prompt: 'Text Recognition:'
      max_new_tokens: 2048
      output_format: text
    vertical_text:
      prompt: 'Text Recognition:'
      max_new_tokens: 2048
      output_format: text
    vision_footnote:
      prompt: 'Text Recognition:'
      max_new_tokens: 1024
      output_format: text
    algorithm:
      prompt: 'Text Recognition:'
      max_new_tokens: 4096
      output_format: text
    doc_title:
      prompt: 'Text Recognition:'
      max_new_tokens: 512
      output_format: text
    paragraph_title:
      prompt: 'Text Recognition:'
      max_new_tokens: 512
      output_format: text
    figure_title:
      prompt: 'Text Recognition:'
      max_new_tokens: 512
      output_format: text
    table:
      prompt: 'Table Recognition:'
      max_new_tokens: 8192
      output_format: html
    display_formula:
      prompt: 'Formula Recognition:'
      max_new_tokens: 2048
      output_format: latex
    inline_formula:
      prompt: 'Text Recognition:'
      max_new_tokens: 1024
      output_format: latex
    formula_number:
      prompt: 'Text Recognition:'
      max_new_tokens: 256
      output_format: text
    header:
      prompt: 'Text Recognition:'
      max_new_tokens: 512
      output_format: text
    footer:
      prompt: 'Text Recognition:'
      max_new_tokens: 512
      output_format: text
    footnote:
      prompt: 'Text Recognition:'
      max_new_tokens: 1024
      output_format: text
    aside_text:
      prompt: 'Text Recognition:'
      max_new_tokens: 1024
      output_format: text
    number:
      prompt: 'Text Recognition:'
      max_new_tokens: 256
      output_format: text
    chart:
      prompt: 'Chart to Table:'
      max_new_tokens: 4096
      output_format: html
    seal:
      prompt: 'Seal Recognition:'
      max_new_tokens: 256
      output_format: text
  default_element:
    prompt: 'Text Recognition:'
    max_new_tokens: 8192
    output_format: text
  slice_nums: 9
  skip_labels:
  - image
  - header_image
  - footer_image
  prompt_reserve: 512
  prompts_source: minicpm-ocr 1.0.1 DEFAULT_PROMPT_MAP
  region_pad: 0
serve:
  server: vllm
  version: 0.32.1rc1.dev602+g5d35ce393
  image: cr.hf.co/davanstrien/minicpm-ocr:1.0-vllm-5d35ce3
  flags:
  - --max-model-len
  - '40960'
  - --max-num-batched-tokens
  - '40960'
  - --max-num-seqs
  - '32'
  - --limit-mm-per-prompt
  - '{"image":36,"video":0}'
  - --mm-processor-kwargs
  - '{"downsample_mode":"4x"}'
  - --trust-request-mm-kwargs
  - --default-chat-template-kwargs
  - '{"enable_thinking":false}'
  draft:
    model: minicpm-ocr-1.0-dspark
    revision: 31e3feaf80e0061cd6aa73db23480d2d691d6452
    speculative:
      method: dspark
      num_speculative_tokens: 15
      enable_adaptive_verification: false
capabilities:
  unit: region
  produces:
  - text
  - html
  - latex
provenance:
  derived_from:
  - pypi:minicpm-ocr==1.0.1:minicpmvocr/configs/minicpmvocr.yaml
  - pypi:minicpm-ocr==1.0.1:minicpmvocr/prompts.py (DEFAULT_PROMPT_MAP)
  - pypi:minicpm-ocr==1.0.1:minicpmvocr/backends/dialects.py (build_vllm_payload)
  - pypi:minicpm-ocr==1.0.1:docs/minicpmvocr_tutorial_en.md (serve flags)
  - finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/minicpm-ocr-port.py
  - openbmb/MiniCPM-OCR-1.0@a59a4acf215e34c6d73149e9eafdb88ed2086e39:README.md
  created: 2026-11-03
support: experimental
---

MiniCPM-OCR 1.0 as a region reader, run the way OpenBMB's SDK (`minicpm-ocr` 1.0.1) runs it: the SDK finds
PP-DocLayoutV3 regions, crops each one from the full-resolution page and sends the crop with the prompt for its
region type. Here the layout comes from linecaster's layout step and `ChatRegionStep` sends the crops.

- Prompt and token cap per region type from the SDK's `DEFAULT_PROMPT_MAP["element_prompts"]`, looked up by
  the layout model's own label (PP-DocLayoutV3's class name, the SDK's vocabulary): `Text Recognition:` for
  text-like regions, `Table Recognition:` (8192 tokens), `Formula Recognition:` for display formulas, `Chart
  to Table:`, `Seal Recognition:`; unknown types get the SDK default (`Text Recognition:`, 8192). Caps are
  clamped to max-model-len - 512 as the SDK does (no effect at 40960).
- Request: the crop, then the prompt; `mm_processor_kwargs` `{"downsample_mode": "4x", "max_slice_nums": 9}`;
  thinking off; temperature 0.01, top_p 0.001, top_k 1, repetition_penalty 1.0, no_repeat_ngram_size 100; PNG.
- Every region is read but the image types (`image`, `header_image`, `footer_image`); charts and seals are
  read (the SDK's chart and seal recognition are on).
- Crop: from the full-resolution page (no page scaling, no padding), the box truncated to whole pixels as
  PaddleX's `CropByBoxes` does, pixels outside the region's polygon white.
- Serve flags from OpenBMB's SDK tutorial (as in the board job), served as `minicpm-ocr`; DSpark speculative
  decoding with the matching draft model (`minicpm-ocr-1.0-dspark`, 15 speculative tokens; mean acceptance
  length about 7 on forge; `--no-speculative` in the recipe turns it off).
- vLLM nightly 5d35ce3 (`0.32.1rc1.dev602+g5d35ce393`) with transformers at OpenBMB's pin: on HF Jobs the
  board's MiniCPM-OCR image. `ninja` must be on PATH or the engine fails at startup.
- `linecaster.models.minicpm_ocr.assemble_markdown` assembles the page with the SDK's own code (extra
  `linecaster[minicpm-ocr]`); the board row kept `footnote` and `aside_text`.

Measured (NOTES.md, "MiniCPM-OCR 1.0 through ChatRegionStep", forge): CER reading 0.0243 on the 60-page sample
against 0.0241 for OpenBMB's SDK on the same server and pages; 39 of 60 pages give byte-identical Markdown.
Not reproduced: the SDK's PaddleX box filtering (`filter_overlap_boxes`) and its merging of aligned text
blocks into one composite crop (`merge_blocks`); linecaster's layout step runs PP-DocLayoutV3's ONNX export
with its own containment suppression. Experimental: validated against the SDK, not the board.
