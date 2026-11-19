Unlimited-OCR on vLLM, following the model card and the uv-scripts recipe `unlimited-ocr-vllm.py`.

- The image, then the text part `document parsing.` (the card's `<image>document parsing.` minus the image
  token: over `/chat/completions` the image is its own content part).
- Full resolution, no resize (the gundam crop grid is chosen from the input pixels): RGB PNG/JPEG bytes as
  they are, anything else RGB PNG.
- Temperature 0.0, max_tokens 8192, `skip_special_tokens` false (the grounding tags must survive), and the
  card's no-repeat n-gram guard per request (`vllm_xargs`, the single-image setting) with its logits processor
  registered at boot, last on the command line (the flag takes a list).
- Serve flags: `--max-model-len 32768 --trust-remote-code`, no prefix caching, no multimodal processor cache,
  one image per prompt. linecaster's vLLM (validated on 0.26.0): the card's dedicated `vllm/vllm-openai:unlimited-ocr` image is obsolete,
  the architecture is registered.
- vLLM 0.29.0, not linecaster's 0.30.0: from 0.30.0 on, vLLM's DeepEncoder attention kernel reads a constant
  Triton refuses ("Cannot access global variable LOG2E"), and the server does not start (2026-11-19; unchanged
  in 0.33.0). The recipe this preset follows names 0.29.0 for the same reason. Back to linecaster's version
  once a vLLM release loads the encoder.
- The completion (grounded output, `<|det|>type [bbox]<|/det|>` headers) is stored verbatim. A response without content is an error, not an empty page.
