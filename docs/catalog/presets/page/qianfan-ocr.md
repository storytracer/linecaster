# qianfan-ocr

*Preset · edition 1 · page · core*

Qianfan-OCR, as the BHL OCR board's driver ran it (built from the card and the checkpoint's config rather than
inherited from Daniel van Strien's `qianfan-ocr.py`).

- The page image, then the card's prompt `Parse this document to Markdown.` (image before text).
- The image bytes as they are, no resize and no conversion, the media type sniffed from the magic bytes: the
  card documents no pixel bounds and the processor tiles and RGB-converts itself (max 12 tiles + a 448-px
  thumbnail). The 60-page sample's lossless WebP decodes to the same pixels as the board's dataset bytes.
- Layout-as-Thought off (`enable_thinking` false per request; the card: disable it for homogeneous pages such
  as book pages).
- Sampling: temperature 0.0 (the card's `do_sample=False`), top_p 1.0, max_tokens 8192.
- Serve flags: `--max-model-len 16384`, one image per prompt, no multimodal processor cache, no prefix caching.
  Not `--trust-remote-code` (the repo ships no code) and not the card's `--hf-overrides` to InternVLChatModel
  (vLLM registers the model natively; the override would run the InternVL code path).
- The completion is stored verbatim; the board's `</think>` strip stays in its harness.
  `--gpu-memory-utilization` is the deployment's choice (board 0.85 on an A10G).

Validated on the 60-page sample (NOTES.md, "Board models as chat specs"): CER reading 0.0482 for linecaster's run on an L4 against 0.0491 for the board's own outputs on the same pages.

```bash
uv run launch.py qianfan-ocr IMAGES OUT
```

|  |  |
|---|---|
| Step | page (reads pages) |
| Engine | [`chat.v1`](../../engines/chat.v1.md) |
| Model | [Qianfan-OCR](../../models/qianfan-ocr.md) |
| Revision | [`623bf5d20d446abdb36606aa4547cd0c18886fe5`](https://huggingface.co/baidu/Qianfan-OCR/tree/623bf5d20d446abdb36606aa4547cd0c18886fe5) |
| Licence | Apache-2.0 |
| Server | vllm 0.26.0 |
| Image | `vllm/vllm-openai:v0.26.0` |
| Produces | markdown |

## Options

| Option | Value |
|---|---|
| adapter | `qianfan-ocr` |

## Evidence

| Date | Source | Dataset | Result |
|---|---|---|---|
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_reading 0.0482 |
| 2026-11-03 | BHL board | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_reading 0.0491 |

## Provenance

- finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/qianfan-ocr-port.py
- baidu/Qianfan-OCR@623bf5d20d446abdb36606aa4547cd0c18886fe5:README.md
