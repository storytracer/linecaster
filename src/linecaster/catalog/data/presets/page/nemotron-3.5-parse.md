Nemotron 3.5 Parse, as the BHL OCR board's driver and its plugin install script ran it, both following the
model card (`docs/serving.md`, "Generation contract" and the H100 `vllm serve` block).

- The control-token prompt `</s><s><predict_bbox><predict_classes><output_markdown><predict_text_in_pic>` as a
  text part FIRST, then the page image (the vendor client).
- RGB at the original size, PNG (the server-side processor fits it to 2048 x 1664; a client-side resize would
  resample twice).
- Sampling: temperature 0.0, top_k 1, repetition_penalty 1.1, max_tokens 8744, `skip_special_tokens` false (the
  reply's coordinate and class tokens are kept).
- Serve flags, the card's H100 block: `--max-model-len 16384 --trust-remote-code --dtype bfloat16
  --distributed-executor-backend uni --max-num-seqs 192 --max-num-batched-tokens 16384`, no prefix caching,
  one image per prompt, `--attention-config '{"flash_attn_version": 3}'`. FlashAttention 3 is a Hopper
  kernel: the board ran on an H200, and an Ada or Ampere GPU (L4, A10G) cannot run these flags as they are.
- The architecture (RadioMBartPrefixForCausalLM) is not in vLLM 0.26.0's registry. NVIDIA serves it through a
  vLLM general plugin (`nemotron-parse` 3.5.0.post7) shipped in the model repo; the adapter's `serve_setup`
  installs it into the vLLM image's own Python before `vllm serve`, as the board's install script does (the
  package source and NVIDIA's inference constraints from the model repo at the pinned revision, the lock's own
  `nemotron-parse` line dropped; the install fails if vLLM moved off 0.26.0). The plugin's one-token MTP
  speculative decoding stays on, as on the board. The image is the board's `vllm/vllm-openai:v0.26.0` by its
  amd64 digest.
- The completion (coordinate tokens, `<class_*>` tokens and Markdown text) is stored verbatim; the board
  renders it with the vendor's `render_markdown` from the model repo in its harness
  (`linecaster.adapters.nemotron_parse35.to_markdown` reproduces it).

Validated on the 60-page sample (NOTES.md, "Board models as chat specs"): CER reading 0.0403 for linecaster's run on an H200 against 0.0454 for the board's own outputs on the same pages.
