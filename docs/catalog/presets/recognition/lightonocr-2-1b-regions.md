# lightonocr-2-1b-regions

*Preset · edition 1 · recognition · experimental*

LightOnOCR-2-1B on layout regions (`RegionRecognizer` after a layout step): each region is cut from the page
scaled to LightOnOCR's 1540-px page size, 8 px around its box at that scale, and sent as it is, with the page
preset's request and sampling.

LightOnOCR-2 is trained on whole pages. On the 60-page sample with PP-DocLayoutV3 regions it loops to its token
limit on 68 of 418 region crops (page headers, footers, footnotes); with those regions left empty the reading
CER is 0.0402 against 0.0285 for whole pages (NOTES.md, "Region recognition with a page model"). Kept as an
experimental way to read regions with a page model; region reading wants a region-trained model
(`minicpm-ocr-1.0`).

|  |  |
|---|---|
| Step | recognition (reads regions) |
| Engine | [`chat.v1`](../../engines/chat.v1.md) |
| Model | [LightOnOCR-2-1B](../../models/lightonocr-2-1b.md) |
| Revision | [`c97bd377f04481830395218fa8951df9deaba756`](https://huggingface.co/lightonai/LightOnOCR-2-1B/tree/c97bd377f04481830395218fa8951df9deaba756) |
| Licence | Apache-2.0 |
| Server | vllm 0.26.0 |
| Image | `vllm/vllm-openai:v0.26.0` |
| Produces | markdown |

## Options

| Option | Value |
|---|---|
| adapter | `lighton-ocr-2` |

## Evidence

| Date | Source | Dataset | Result |
|---|---|---|---|
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_reading 0.0402 |

## Provenance

- finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/lighton-ocr2-port.py
- uv-scripts/ocr@4ae561fcfef053f60c310cd04f7a7fa0e2fadce2:lighton-ocr2-saturate.py
- lightonai/LightOnOCR-2-1B@c97bd377f04481830395218fa8951df9deaba756:README.md
