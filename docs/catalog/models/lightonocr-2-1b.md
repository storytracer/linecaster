# lightonocr-2-1b

*Model · LightOnOCR-2-1B · Apache-2.0*

LightOnOCR-2-1B is LightOn's end-to-end 1B vision-language OCR model (arXiv 2601.14251): it turns a page image
into clean, naturally ordered text (with LaTeX for maths) without a separate layout pipeline. It is the
RLVR-refined variant of the LightOnOCR-2 family; LightOnOCR-2-1B-base (for fine-tuning) and bbox variants that
also predict image boxes are separate repositories. The card does not name the checkpoint it was trained from,
so `derived_from` is empty. Licence: Apache-2.0.
The upstream card is in `upstream/c97bd377f04481830395218fa8951df9deaba756/README.md`.

|  |  |
|---|---|
| Source | [lightonai/LightOnOCR-2-1B](https://huggingface.co/lightonai/LightOnOCR-2-1B) |
| Licence | Apache-2.0 |
| Languages | eng, fra, deu, spa, ita, nld, por, swe, dan, zho, jpn |
| Scripts | Latn, Hani, Jpan |
| Parameters | 1B |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `c97bd377f04481830395218fa8951df9deaba756` | 2026-11-03 |  | 4 | [README.md](../../../src/linecaster/catalog/data/models/lightonocr-2-1b/upstream/c97bd377f04481830395218fa8951df9deaba756/README.md) |

## Presets

- [`lightonocr-2-1b`](../presets/page/lightonocr-2-1b.md)
- [`lightonocr-2-1b-regions`](../presets/recognition/lightonocr-2-1b-regions.md)
