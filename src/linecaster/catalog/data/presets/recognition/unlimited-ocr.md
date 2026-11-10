Unlimited-OCR on vLLM, following the model card and the uv-scripts recipe `unlimited-ocr-vllm.py`.

- The image, then the text part `document parsing.` (the card's `<image>document parsing.` minus the image
  token: over `/chat/completions` the image is its own content part).
- Full resolution, no resize (the gundam crop grid is chosen from the input pixels): RGB PNG/JPEG bytes as
  they are, anything else RGB PNG.
- Temperature 0.0, max_tokens 8192, `skip_special_tokens` false (the grounding tags must survive), and the
  card's no-repeat n-gram guard per request (`vllm_xargs`, the single-image setting) with its logits processor
  registered at boot, last on the command line (the flag takes a list).
- Serve flags: `--max-model-len 32768 --trust-remote-code`, no prefix caching, no multimodal processor cache,
  one image per prompt. vLLM 0.26.0: the card's dedicated `vllm/vllm-openai:unlimited-ocr` image is obsolete,
  the architecture is registered.
- The completion (grounded output, `<|det|>type [bbox]<|/det|>` headers) is stored verbatim. A response without content is an error, not an empty page.

Validated against a reference implementation's outputs on a 60-page sample of historic print (NOTES.md, "Chat
presets: validation on the 60-page sample").
