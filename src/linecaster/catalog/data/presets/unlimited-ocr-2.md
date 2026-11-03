---
schema: linecaster.preset/1
id: unlimited-ocr-2
edition: 1
step: page
model:
  id: unlimited-ocr-2
  revision: 9cf077c4b206e0e2a31879df937b0b0bcba3661c
engine:
  kind: chat/1
  options:
    adapter: unlimited-ocr-2
    served_name: Unlimited-OCR-2
    revision_flag: false
    pin_ignore:
    - README.md
    - .gitattributes
    - wheel/*
    - '*.pdf'
    server_packages:
    - - --no-deps
      - https://huggingface.co/{repo}/resolve/{revision}/wheel/sglang-0.5.20.dev10%2Bg8d62f5fb9c-py3-none-any.whl
    - - fastokens==0.3.2
settings:
  sampling:
    max_tokens: 8000
    temperature: 0.0
    skip_special_tokens: false
  prompt: <PAGE><image>Multi page parsing.
  images_config:
    crop_mode: true
  custom_logit_processor: '{"callable": "80059559000000000000008c2a73676c616e672e7372742e73616d706c696e672e637573746f6d5f6c6f6769745f70726f636573736f72948c26446565707365656b4f43524e6f5265706561744e4772616d4c6f67697450726f636573736f729493942e"}'
  custom_params:
    ngram_size: 35
    window_size: 128
    page_token_id: 128827
    eos_token_id: 1
    max_page_tokens: 20000
serve:
  server: sglang
  version: 0.5.20.dev10+g8d62f5fb9c
  image: lmsysorg/sglang:v0.5.20-cu130
  flags:
  - --chat-template
  - unlimited-ocr
  - --tokenizer-backend
  - fastokens
  - --tokenizer-worker-num
  - '8'
  - --mem-fraction-static
  - '0.7'
  - --max-running-requests
  - '64'
  - --max-prefill-tokens
  - '2048'
  - --enable-custom-logit-processor
  - --enable-streaming-session
  - --allow-auto-truncate
  - --disable-radix-cache
  - --mm-preprocess-cache-size-mb
  - '0'
  - --cuda-graph-backend-decode
  - full
  - --cuda-graph-max-bs-decode
  - '64'
  - --cuda-graph-backend-prefill
  - full
  - --cuda-graph-max-bs-prefill
  - '16384'
  - --cuda-graph-bs-prefill
  - '1024'
  - '2048'
  - --cuda-graph-config
  - '{"prefill": {"backend": "full", "full_prefill_max_req": 64}}'
  env:
    SGLANG_UOCR_EANABLE_DOC_LIMIT: '1'
    SGLANG_UOCR_DOC_GUNDAM_PAGE_WINDOW: '10'
    SGLANG_UOCR_DOC_BASE_PAGE_WINDOW: '10'
    SGLANG_UOCR_MAX_PAGE_TOKENS: '20000'
    SGLANG_OPT_UOCR_SAM_REL_POS_BIAS_MB: '64'
    SGLANG_UOCR_SHM_WRAP_MODEL_DATA: '1'
    SGLANG_UOCR_SHM_WRAP_MIN_MB: '1'
    SGLANG_VLM_CACHE_SIZE_MB: '0'
    PYTORCH_CUDA_ALLOC_CONF: expandable_segments:True
capabilities:
  unit: page
  produces:
  - text
provenance:
  derived_from:
  - finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/unlimited-ocr2-port.py
  - uv-scripts/ocr@4ae561fcfef053f60c310cd04f7a7fa0e2fadce2:unlimited-ocr2-saturate.py
  - baidu/Unlimited-OCR-2@9cf077c4b206e0e2a31879df937b0b0bcba3661c:README.md
  created: 2026-11-03
support: core
---

Unlimited-OCR-2 on Baidu's patched SGLang, as the BHL OCR board's driver ran it. No vLLM support exists for it.

- Server: SGLang in the image's own Python (`lmsysorg/sglang:v0.5.20-cu130`), with Baidu's wheel
  (`sglang-0.5.20.dev10+g8d62f5fb9c`, read from the model repo at the pinned revision) installed `--no-deps`
  and `fastokens==0.3.2` first; served as `Unlimited-OCR-2`; the card's launch environment and flags, plus
  `--enable-metrics` (saturate reads SGLang's queue gauges). `SGLANG_UOCR_EANABLE_DOC_LIMIT` is upstream's
  spelling. `serve.version` is the wheel's version, which is the SGLang that runs.
- No `--revision`: with it, Baidu's SGLang skips its tokenizer fix-up and fastokens refuses the tokenizer at
  boot, so the server loads the default branch. The board refused to start unless the default branch was the
  pinned commit; it has since moved on (README and a newer wheel only), so the serve block checks instead that
  every file on the default branch other than README, `.gitattributes`, `wheel/` and the paper PDF equals the
  pinned revision's (git blob ids).
- The image, then `<PAGE><image>Multi page parsing.` (card-verbatim, the same prompt for one page as for
  many); full resolution, the same passthrough rule as v1.
- max_tokens 8000, temperature 0.0, `skip_special_tokens` false, `images_config {"crop_mode": true}` (gundam,
  the card's single-page default), and the card's no-repeat n-gram guard as an SGLang custom logit processor
  (`DeepseekOCRNoRepeatNGramLogitProcessor`, by its dill pickle reference) with its parameters.
- The completion (`<BLOCK>type[x1, y1, x2, y2]<FORK>text` blocks) is stored verbatim; the board scores it after
  Baidu's own Markdown converter, which stays in its harness. A response without content is an error.
- The board ran it on an RTX PRO 6000 (96 GB) with the card's flags for an 80 GB A800
  (`--mem-fraction-static 0.7`, CUDA graphs up to 16384 prefill tokens).

Validated on the 60-page sample (NOTES.md, "Board models as chat specs"): CER reading 0.0251 for linecaster's run on an L4 against 0.0262 for the board's own outputs on the same pages.
