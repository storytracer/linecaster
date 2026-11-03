---
schema: linecaster.model/1
id: nemotron-3.5-parse
version: Nemotron 3.5 Parse
source:
  kind: hf
  ref: nvidia/Nemotron-3.5-Parse
pins:
- revision: 62cb1e4ba153d113ff64aaf2be6e068c377cf53c
  pinned: 2026-11-03
  files:
    model.safetensors: sha256:81dd7609c589f3694ce75520c25af5010953231358de6aec4d03e8c6aac787e9
    reference/parsebench/paddle_optimized/predictions.jsonl.gz: sha256:e7eb3cc72209f7f5e38b226cb9e2c6025051ed4b686b2b9040fd39cd59e3248f
    reference/parsebench/reference_results/mtp/predictions.jsonl.gz: sha256:64d61579fa98ca6e252a492b3a662b0e7858c84a7712b4fa0e5c3d951e500e12
    reference/parsebench/reference_results/no_mtp/predictions.jsonl.gz: sha256:c65fbc4ce76a84b46fe752cc4e0cbc64a7217bd196e2034ad90769a353676e8a
  card: upstream/62cb1e4ba153d113ff64aaf2be6e068c377cf53c/README.md
  card_sha256: sha256:5a449f1bd9f6f00577c741cf2782579c99600d6315cd1ea54d82db6264003376
  license_file: upstream/62cb1e4ba153d113ff64aaf2be6e068c377cf53c/LICENSE
license: OpenMDW-1.1
languages:
- mul
scripts: []
params: 0.631B
derived_from: []
---

Nemotron 3.5 Parse is NVIDIA's document image parser: one string per page with text, semantic layout classes,
bounding boxes and reading order (Markdown text by default; upstream helpers render Markdown with HTML tables,
or LaTeX/HTML/JSON/CSV tables). It combines a C-RADIOv4-SO400M vision encoder with a 10-layer mBART decoder,
about 0.631B parameters; the card names no base checkpoint. The card reports multilingual evaluation (10 Indic
languages; 163 language/script entries in 26 script groups on synthetic pages) but no list of supported
languages, so `languages` is `mul` and `scripts` is empty. Licence: OpenMDW License Agreement 1.1 for the
weights (copied as `upstream/62cb1e4ba153d113ff64aaf2be6e068c377cf53c/LICENSE`); the bundled tokenizer is MIT.
The upstream card is in `upstream/62cb1e4ba153d113ff64aaf2be6e068c377cf53c/README.md`.
