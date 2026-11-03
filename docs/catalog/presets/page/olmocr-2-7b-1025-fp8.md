# olmocr-2-7b-1025-fp8

*Preset · edition 1 · page · experimental*

olmOCR-2-7B-1025-FP8, as the BHL OCR board's driver ran it (a port of Daniel van Strien's `olmocr2-vllm.py`;
where the two differ, the driver wins).

- The olmOCR no-anchoring (v4, YAML) prompt as a text part, THEN the page image (text before image, as the
  driver sends it).
- PNG with the longest side forced to exactly 1288 px, up or down (the olmOCR pipeline's
  `target_longest_image_dim`), LANCZOS.
- Sampling: temperature 0.1, max_tokens 8192, repetition_penalty 1.05, stop `<|im_end|>`, `<|endoftext|>` (the
  recipe's values, recorded in the driver).
- Serve flags: `--max-model-len 16384`, no prefix caching, no multimodal processor cache, one image per prompt;
  no `--trust-remote-code`. vLLM 0.26.0 (the board's; Daniel's recipe has since moved to 0.29.0).
- The model answers with YAML front matter (primary_language, is_rotation_valid, rotation_correction, is_table,
  is_diagram) above the page text. The completion is stored verbatim and the front matter also parsed into
  `extra["front_matter"]`; dropping it from the scored text is the board's post-processing, left to the
  harness (`linecaster.models.olmocr2.body` gives the same split). Not yet run by linecaster: experimental.

|  |  |
|---|---|
| Step | page (reads pages) |
| Engine | [`chat.v1`](../../engines/chat.v1.md) |
| Model | [olmOCR-2-7B-1025-FP8](../../models/olmocr-2-7b-1025-fp8.md) |
| Revision | [`40bd7202494b8264ee17ada08b401b5aab7a9ce1`](https://huggingface.co/allenai/olmOCR-2-7B-1025-FP8/tree/40bd7202494b8264ee17ada08b401b5aab7a9ce1) |
| Licence | Apache-2.0 |
| Server | vllm 0.26.0 |
| Image | `vllm/vllm-openai:v0.26.0` |
| Produces | markdown |

## Options

| Option | Value |
|---|---|
| adapter | `olmocr` |

## Provenance

- finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/olmocr2-port.py
- uv-scripts/ocr@4ae561fcfef053f60c310cd04f7a7fa0e2fadce2:olmocr2-vllm.py
- allenai/olmOCR-2-7B-1025-FP8@40bd7202494b8264ee17ada08b401b5aab7a9ce1:README.md
