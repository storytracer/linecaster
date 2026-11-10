Unlimited-OCR-2 on Baidu's patched SGLang, following the model card. No vLLM support exists for it.

- Server: SGLang in the image's own Python (`lmsysorg/sglang:v0.5.20-cu130`), with Baidu's wheel
  (`sglang-0.5.20.dev10+g8d62f5fb9c`, read from the model repo at the pinned revision) installed `--no-deps`
  and `fastokens==0.3.2` first; served as `Unlimited-OCR-2`; the card's launch environment and flags, plus
  `--enable-metrics` (saturate reads SGLang's queue gauges). `SGLANG_UOCR_EANABLE_DOC_LIMIT` is upstream's
  spelling. `serve.version` is the wheel's version, which is the SGLang that runs.
- No `--revision`: with it, Baidu's SGLang skips its tokenizer fix-up and fastokens refuses the tokenizer at
  boot, so the server loads the default branch. The default branch has moved on from the pinned commit (README
  and a newer wheel only), so the serve block checks that every file on the default branch other than README,
  `.gitattributes`, `wheel/` and the paper PDF equals the pinned revision's (git blob ids).
- The image, then `<PAGE><image>Multi page parsing.` (card-verbatim, the same prompt for one page as for
  many); full resolution, the same passthrough rule as v1.
- max_tokens 8000, temperature 0.0, `skip_special_tokens` false, `images_config {"crop_mode": true}` (gundam,
  the card's single-page default), and the card's no-repeat n-gram guard as an SGLang custom logit processor
  (`DeepseekOCRNoRepeatNGramLogitProcessor`, by its dill pickle reference) with its parameters.
- The completion (`<BLOCK>type[x1, y1, x2, y2]<FORK>text` blocks) is stored verbatim; Baidu's own Markdown
  converter is left to whoever reads the output. A response without content is an error.
- The card's flags are for an 80 GB A800 (`--mem-fraction-static 0.7`, CUDA graphs up to 16384 prefill tokens);
  they also run on a 96 GB card.

Validated against a reference implementation's outputs on a 60-page sample of historic print (NOTES.md, "Chat
presets: validation on the 60-page sample").
