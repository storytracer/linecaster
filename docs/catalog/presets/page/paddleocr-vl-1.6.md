# paddleocr-vl-1.6

*Preset · edition 1 · page · core*

PaddleOCR-VL-1.6's VLM alone on the whole page (task mode `ocr`), as the BHL OCR board's driver ran it (a port
of Daniel van Strien's `paddleocr-vl-1.6.py`), not PaddleOCR-VL's PP-DocLayout + VLM pipeline.

- The page image, then the text part `OCR:`.
- RGB, resized client-side by the recipe's `smart_resize`: both sides rounded to multiples of 28, the area
  brought into [28·28·130, 28·28·1280] px (floor when shrinking, ceil when growing; aspect kept), LANCZOS,
  PNG; an image already on that grid is sent unresized (still re-encoded as PNG).
- Temperature 0.0, max_tokens 4096.
- Serve flags: `--max-model-len 8192 --trust-remote-code --enforce-eager --max-num-batched-tokens 16384`, no
  prefix caching, no multimodal processor cache, one image per prompt.
- The completion is stored verbatim; the board's strip stays in its harness.

Validated on the 60-page sample (NOTES.md, "Board models as chat specs"): CER reading 0.0309 for linecaster's run on an L4 against 0.0309 for the board's own outputs on the same pages. Greedy decoding with identical requests
reproduces the board exactly.

```bash
uv run launch.py paddleocr-vl-1.6 IMAGES OUT
```

|  |  |
|---|---|
| Step | page (reads pages) |
| Engine | [`chat.v1`](../../engines/chat.v1.md) |
| Model | [PaddleOCR-VL-1.6](../../models/paddleocr-vl-1.6.md) |
| Revision | [`66317acc4c9fc17bd154591ce650735cd2855f3e`](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/tree/66317acc4c9fc17bd154591ce650735cd2855f3e) |
| Licence | Apache-2.0 |
| Server | vllm 0.26.0 |
| Image | `vllm/vllm-openai:v0.26.0` |
| Produces | text |

## Options

| Option | Value |
|---|---|
| adapter | `paddleocr-vl` |

## Evidence

| Date | Source | Dataset | Result |
|---|---|---|---|
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_reading 0.0309 |
| 2026-11-03 | BHL board | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_reading 0.0309 |

## Provenance

- finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/paddleocr-vl-16-port.py
- uv-scripts/ocr@4ae561fcfef053f60c310cd04f7a7fa0e2fadce2:paddleocr-vl-1.6.py
- PaddlePaddle/PaddleOCR-VL-1.6@66317acc4c9fc17bd154591ce650735cd2855f3e:README.md
