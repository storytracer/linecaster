# unlimited-ocr-2

*Preset · edition 1 · page · core*

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

|  |  |
|---|---|
| Step | page (reads pages) |
| Engine | [`chat.v1`](../../engines/chat.v1.md) |
| Model | [Unlimited-OCR 2](../../models/unlimited-ocr-2.md) |
| Revision | [`9cf077c4b206e0e2a31879df937b0b0bcba3661c`](https://huggingface.co/baidu/Unlimited-OCR-2/tree/9cf077c4b206e0e2a31879df937b0b0bcba3661c) |
| Licence | MIT |
| Server | sglang 0.5.20.dev10+g8d62f5fb9c |
| Image | `lmsysorg/sglang:v0.5.20-cu130` |
| Produces | text |

## Options

| Option | Value |
|---|---|
| adapter | `unlimited-ocr-2` |
| served_name | `Unlimited-OCR-2` |

## Evidence

| Date | Source | Dataset | Result |
|---|---|---|---|
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_reading 0.0251 |
| 2026-11-03 | BHL board | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_reading 0.0262 |

## Provenance

- finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/unlimited-ocr2-port.py
- uv-scripts/ocr@4ae561fcfef053f60c310cd04f7a7fa0e2fadce2:unlimited-ocr2-saturate.py
- baidu/Unlimited-OCR-2@9cf077c4b206e0e2a31879df937b0b0bcba3661c:README.md
