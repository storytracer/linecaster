# glm-ocr

*Model · GLM-OCR · MIT*

GLM-OCR is Z.ai's (`zai-org`) 0.9B OCR model for complex documents, on the GLM-V encoder-decoder architecture:
a CogViT vision encoder, a light connector and a GLM-0.5B language decoder (arXiv 2603.10910). It recognises
text, formulas and tables (Markdown output) and does schema-driven information extraction to JSON. Upstream
runs it in a two-stage pipeline: PP-DocLayoutV3 layout analysis, then parallel recognition of the regions. The
card names no base checkpoint. Licence: MIT for the model; PP-DocLayoutV3 in the full pipeline is Apache-2.0.
The upstream card is in `upstream/ca5d8b3e287e52589e37c28385d9655ee4372f9d/README.md`.

|  |  |
|---|---|
| Source | [zai-org/GLM-OCR](https://huggingface.co/zai-org/GLM-OCR) |
| Licence | MIT |
| Languages | zho, eng, fra, spa, rus, deu, jpn, kor |
| Scripts | Hani, Latn, Cyrl, Jpan, Kore |
| Parameters | 0.9B |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `ca5d8b3e287e52589e37c28385d9655ee4372f9d` | 2026-11-03 |  | 1 | [README.md](../../../src/linecaster/catalog/data/models/glm-ocr/upstream/ca5d8b3e287e52589e37c28385d9655ee4372f9d/README.md) |

## Presets

- [`glm-ocr`](../presets/recognition/glm-ocr.md)
