MiniCPM-OCR 1.0 as a region reader, run the way OpenBMB's SDK (`minicpm-ocr` 1.0.1) runs it: the SDK finds
PP-DocLayoutV3 regions, crops each one from the full-resolution page and sends the crop with the prompt for its
region type. Here the layout comes from linecaster's layout step and `RegionRecognizer` sends the crops.

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
- `linecaster.adapters.minicpm_ocr.assemble_markdown` assembles the page with the SDK's own code (extra
  `linecaster[minicpm-ocr]`); the board row kept `footnote` and `aside_text`.

Measured (NOTES.md, "MiniCPM-OCR 1.0 through RegionRecognizer", forge): CER reading 0.0243 on the 60-page sample
against 0.0241 for OpenBMB's SDK on the same server and pages; 39 of 60 pages give byte-identical Markdown.
Not reproduced: the SDK's PaddleX box filtering (`filter_overlap_boxes`) and its merging of aligned text
blocks into one composite crop (`merge_blocks`); linecaster's layout step runs PP-DocLayoutV3's ONNX export
with its own containment suppression. Experimental: validated against the SDK, not the board.
