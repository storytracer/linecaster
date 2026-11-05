DeepSeek-OCR in grounded document mode, as the BHL OCR board's driver ran it (a port of Daniel van
Strien's `deepseek-ocr-vllm.py`; the DeepSeek-OCR and DeepSeek-OCR-2 drivers are twins and differ only in the checkpoint).

- The prompt `<|grounding|>Convert the document to markdown.` as a text part after the image (the recipe's raw
  `<image>\n<|grounding|>...` prompt becomes image + text; the chat template inserts the image token).
- No resolution mode is passed (no `mm_processor_kwargs`), so vLLM's default applies: Gundam (base 1024, tiles
  of 640, crop mode, up to 6 crops), the mode the card recommends for documents.
- Full resolution, no resize: RGB PNG/JPEG bytes as they are, anything else RGB PNG.
- Sampling: temperature 0.0, max_tokens 4096 (8192 context minus the image), `skip_special_tokens` false so the
  grounding tags survive.
- The card's n-gram repetition guard: `--logits_processors
  vllm.model_executor.models.deepseek_ocr:NGramPerReqLogitsProcessor` at boot (last on the command line: the
  flag takes a list) and `vllm_xargs` per request (the whitelist is `<td>`/`</td>` in v1's tokenizer; v2 uses
  v1's processor and whitelist, as the v2 vLLM recipe does; that the ids are the same tokens in v2's tokenizer
  is not verified).
- Serve flags: `--max-model-len 8192` (the native context), `--trust-remote-code`, no prefix caching, no
  multimodal processor cache, one image per prompt.
- The completion is stored verbatim, grounding markup included; the board's `deepseek_strip_grounding`
  (postproc 3) stays in its harness, `linecaster.adapters.deepseek_ocr.strip_grounding` is the same rule.
  `--gpu-memory-utilization` is the deployment's choice (board 0.8 on an A10G).

Validated on the 60-page sample (NOTES.md, "Board models as chat specs"): CER reading 0.0551 for linecaster's run on an L4 against 0.0543 for the board's own outputs on the same pages.
