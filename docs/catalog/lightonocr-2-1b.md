# lightonocr-2-1b

*Edition 1 · page · experimental*

LightOnOCR-2-1B on whole pages, exactly as the BHL OCR board's saturate driver ran it (a port of Daniel van
Strien's `lighton-ocr2-saturate.py`).

- The page image only, no text part: LightOnOCR-2's trained format, per the card.
- PNG with the longest side forced to exactly 1540 px, up or down (the card's target longest dimension;
  `processor_config` longest_edge 1540).
- Sampling from the card: temperature 0.2, top_p 0.9, max_tokens 4096.
- Serve flags: the card's three (one image per prompt, no multimodal processor cache, no prefix caching) plus
  `--max-model-len 16384` (the board's; the model's native context). No `--trust-remote-code`: the
  architecture is registered in vLLM.
- The completion is stored verbatim; the board's strip stays in its harness. `--gpu-memory-utilization` is
  the deployment's choice (board 0.8 on an A10G).

Measured (NOTES.md, "Chat VLMs: LightOnOCR-2-1B through ChatPageStep"): CER reading 0.0285 on the 60-page
sample against 0.0321 for the board's outputs, on vLLM 0.21.0 rather than the board's 0.26.0; sampling at
temperature 0.2 makes runs differ (0.026-0.030 between runs). Experimental: not part of the board validation
table on 0.26.0.

| | |
|---|---|
| Step | page (reads pages) |
| Engine | `chat/1` |
| Model | [LightOnOCR-2-1B](https://huggingface.co/lightonai/LightOnOCR-2-1B/tree/c97bd377f04481830395218fa8951df9deaba756) |
| Revision | `c97bd377f04481830395218fa8951df9deaba756` |
| Upstream card | [upstream/c97bd377f04481830395218fa8951df9deaba756/README.md](../../src/linecaster/catalog/data/models/lightonocr-2-1b/upstream/c97bd377f04481830395218fa8951df9deaba756/README.md) (verbatim, at that revision) |
| Licence | Apache-2.0 |
| Languages | eng, fra, deu, spa, ita, nld, por, swe, dan, zho, jpn |
| Scripts | Latn, Hani, Jpan |
| Server | vllm 0.26.0 |
| Image | `vllm/vllm-openai:v0.26.0` |
| Produces | markdown |

## Evidence

| Date | Source | Dataset | Result |
|---|---|---|---|
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_reading 0.0372, cer_dip 0.0738 |
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_reading 0.0285, cer_dip 0.0614, recall 0.9717 |
| 2026-11-03 | BHL board | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_reading 0.0321, cer_dip 0.0656, recall 0.9666 |

## Provenance

- finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/lighton-ocr2-port.py
- uv-scripts/ocr@4ae561fcfef053f60c310cd04f7a7fa0e2fadce2:lighton-ocr2-saturate.py
- lightonai/LightOnOCR-2-1B@c97bd377f04481830395218fa8951df9deaba756:README.md
