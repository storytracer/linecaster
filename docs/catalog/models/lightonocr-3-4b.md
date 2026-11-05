# lightonocr-3-4b

*Model · LightOnOCR-3-4B · Apache-2.0*

LightOnOCR-3-4B is the largest model of LightOn's LightOnOCR-3 family of end-to-end OCR models. With an empty
prompt it transcribes the page as Markdown (as LightOnOCR-2 did); with the `grounding` prompt each block comes
with a label and a bounding box (0-1000 page coordinates), images get a short description and charts an HTML
table of their data. It uses the Qwen3.5 vision-language architecture (loaded with the Qwen3.5 classes,
thinking disabled); the card names no base checkpoint and its front matter lists no languages. Licence:
Apache-2.0, for research and commercial use.
The upstream card is in `upstream/b71010f095dc3735de7ee6b9969bff8f8f50b39a/README.md`.

|  |  |
|---|---|
| Source | [lightonai/LightOnOCR-3-4B](https://huggingface.co/lightonai/LightOnOCR-3-4B) |
| Licence | Apache-2.0 |
| Parameters | 4B |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `b71010f095dc3735de7ee6b9969bff8f8f50b39a` | 2026-11-03 |  | 3 | [README.md](../../../src/linecaster/catalog/data/models/lightonocr-3-4b/upstream/b71010f095dc3735de7ee6b9969bff8f8f50b39a/README.md) |

## Presets

- [`lightonocr-3-4b`](../presets/recognition/lightonocr-3-4b.md)
