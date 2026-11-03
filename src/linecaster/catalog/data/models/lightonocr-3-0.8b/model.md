---
schema: linecaster.model/1
id: lightonocr-3-0.8b
version: LightOnOCR-3-0.8B
source:
  kind: hf
  ref: lightonai/LightOnOCR-3-0.8B
pins:
- revision: 36d8636925327c671bd8e479c517a004f7566bd9
  pinned: 2026-11-03
  files:
    lightonocr3_logo.png: sha256:768eee79d378518cfea9ed8d81ba3a53a0cff17ccf4b12c22a9e5ebedde32bcf
    model.safetensors: sha256:ae46aa6fd7136d57297ac006ed9ec345b7a2083feb2e99501bedcb014ca3efdf
    tokenizer.json: sha256:06b9509352d2af50381ab2247e083b80d32d5c0aba91c272ca9ff729b6a0e523
  card: upstream/36d8636925327c671bd8e479c517a004f7566bd9/README.md
  card_sha256: sha256:0df44eab78278bad416d8974e96a6a181d59bae8416fa54877bd5b022e76aaf2
license: Apache-2.0
languages:
- eng
scripts:
- Latn
params: 0.8B
derived_from: []
---

LightOnOCR-3-0.8B is the smallest model of LightOn's LightOnOCR-3 family of end-to-end OCR models, with the
same features as the 4B: an empty prompt gives the page as Markdown, the `grounding` prompt adds a label and a
bounding box (0-1000 page coordinates) per block, image descriptions and chart data as HTML tables. It uses
the Qwen3.5 vision-language architecture (loaded with the Qwen3.5 classes, thinking disabled); the card names
no base checkpoint. Its front matter lists English only. Licence: Apache-2.0, for research and commercial use.
The upstream card is in `upstream/36d8636925327c671bd8e479c517a004f7566bd9/README.md`.
